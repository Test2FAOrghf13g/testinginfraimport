"""Support for restoring entity states on startup."""
import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant, CoreState, callback, State
from homeassistant.const import (
    EVENT_HOMEASSISTANT_START, EVENT_HOMEASSISTANT_STOP)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.json import JSONEncoder
from homeassistant.helpers.storage import Store
from homeassistant.loader import bind_hass

DATA_RESTORE_CACHE = 'restore_state_cache'
DATA_RESTORE_STORAGE = 'restore_state_store'
_LOCK = 'restore_lock'
_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = 'core.restore_state'
STORAGE_VERSION = 1

# How long between periodically saving the current states to disk
STATE_DUMP_INTERVAL = timedelta(hours=1)


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


async def _load_restore_cache(hass: HomeAssistant) -> None:
    """Load the restore cache to be used by other components."""
    @callback
    def remove_cache(event):
        """Remove the states cache."""
        hass.data.pop(DATA_RESTORE_CACHE, None)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, remove_cache)

    store = _get_restore_state_store(hass)

    states = await store.async_load()
    if states is None:
        _LOGGER.debug('Not creating cache - no saved states found')
        hass.data[DATA_RESTORE_CACHE] = {}
        return

    hass.data[DATA_RESTORE_CACHE] = {
        state['entity_id']: State.from_dict(state) for state in states}
    _LOGGER.debug('Created cache with %s', list(hass.data[DATA_RESTORE_CACHE]))


def _get_restore_state_store(hass: HomeAssistant) -> Store:
    """Return the data store for the last session's states."""
    if DATA_RESTORE_STORAGE not in hass.data:
        hass.data[DATA_RESTORE_STORAGE] = hass.helpers.storage.Store(
            STORAGE_VERSION, STORAGE_KEY, encoder=JSONEncoder)

    return hass.data[DATA_RESTORE_STORAGE]


@bind_hass
async def async_get_last_state(hass: HomeAssistant, entity_id: str) -> State:
    """Restore state."""
    if DATA_RESTORE_CACHE in hass.data:
        return hass.data[DATA_RESTORE_CACHE].get(entity_id)

    if hass.state not in (CoreState.starting, CoreState.not_running):
        _LOGGER.debug("Cache for %s can only be loaded during startup, not %s",
                      entity_id, hass.state)
        return None

    if _LOCK not in hass.data:
        hass.data[_LOCK] = asyncio.Lock(loop=hass.loop)

    async with hass.data[_LOCK]:
        try:
            if DATA_RESTORE_CACHE not in hass.data:
                await _load_restore_cache(hass)
        except HomeAssistantError:
            return None

    return hass.data.get(DATA_RESTORE_CACHE, {}).get(entity_id)


async def async_restore_state(entity: Entity, extract_info: dict) -> None:
    """Call entity.async_restore_state with cached info."""
    if entity.hass.state not in (CoreState.starting, CoreState.not_running):
        _LOGGER.debug("Not restoring state for %s: Hass is not starting: %s",
                      entity.entity_id, entity.hass.state)
        return

    state = await async_get_last_state(entity.hass, entity.entity_id)

    if not state:
        return

    await entity.async_restore_state(**extract_info(state))


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
