"""Support for restoring entity states on startup."""
import logging
from datetime import timedelta
from typing import Dict, Optional

from homeassistant.core import HomeAssistant, CoreState, callback, State
from homeassistant.const import (
    EVENT_HOMEASSISTANT_START, EVENT_HOMEASSISTANT_STOP)
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.json import JSONEncoder
from homeassistant.helpers.storage import Store
from homeassistant.loader import bind_hass

DATA_RESTORE_STORAGE = 'restore_state_store'
DATA_RESTORE_CACHE_TASK = 'restore_state_store_task'

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = 'core.restore_state'
STORAGE_VERSION = 1

# How long between periodically saving the current states to disk
STATE_DUMP_INTERVAL = timedelta(minutes=15)


@callback
def async_setup(hass: HomeAssistant) -> None:
    """Set up the event listeners for state restoration."""
    @callback
    def async_add_dump_states_job(*args):
        """Set up the restore state listeners."""
        hass.async_create_task(async_dump_states(hass))

    @callback
    def async_setup_restore_state(*args):
        """Set up the restore state listeners."""
        # Dump the initial states now. This helps minimize the risk of having
        # old states loaded by overwritting the last states once home assistant
        # has started.
        async_add_dump_states_job()

        # Dump states periodically
        async_track_time_interval(
            hass, async_add_dump_states_job, STATE_DUMP_INTERVAL)

        # Dump states when stopping hass
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, async_add_dump_states_job)

    hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_START, async_setup_restore_state)


async def async_get_restore_cache(hass: HomeAssistant) -> Dict[str, State]:
    """Get the restore cache for loading previous states."""
    task = hass.data.get(DATA_RESTORE_CACHE_TASK)

    if task is None:
        async def _load_restore_cache(hass: HomeAssistant) -> Dict[str, State]:
            """Load the restore cache to be used by other components."""
            store = _get_restore_state_store(hass)

            states = await store.async_load()
            if states is None:
                _LOGGER.debug('Not creating cache - no saved states found')
                return {}

            cache = {
                state['entity_id']: State.from_dict(state) for state in states}
            _LOGGER.debug('Created cache with %s', list(cache))

            return cache

        task = hass.data[DATA_RESTORE_CACHE_TASK] = hass.async_create_task(
            _load_restore_cache(hass))

    return await task


def _get_restore_state_store(hass: HomeAssistant) -> Store:
    """Return the data store for the last session's states."""
    if DATA_RESTORE_STORAGE not in hass.data:
        hass.data[DATA_RESTORE_STORAGE] = hass.helpers.storage.Store(
            STORAGE_VERSION, STORAGE_KEY, encoder=JSONEncoder)

    return hass.data[DATA_RESTORE_STORAGE]


@bind_hass
async def async_get_last_state(
        hass: HomeAssistant, entity_id: str) -> Optional[State]:
    """Restore state."""
    if hass.state not in (CoreState.starting, CoreState.not_running):
        _LOGGER.debug("Cache for %s can only be loaded during startup, not %s",
                      entity_id, hass.state)
        return None

    cache = await async_get_restore_cache(hass)

    return cache.get(entity_id)


@bind_hass
async def async_dump_states(hass: HomeAssistant) -> None:
    """Save the current state machine to storage."""
    _LOGGER.debug("Dumping states")
    store = _get_restore_state_store(hass)
    try:
        await store.async_save([
            state.as_dict() for state in hass.states.async_all()])
    except HomeAssistantError as exc:
        _LOGGER.error("Error saving current states", exc_info=exc)
