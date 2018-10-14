"""The tests for the Restore component."""
from unittest.mock import patch

from homeassistant.core import CoreState, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.restore_state import (
    RestoreStateData, async_get_last_state, DATA_RESTORE_STATE_TASK)


async def test_caching_data(hass):
    """Test that we cache data."""
    hass.state = CoreState.starting

    states = [
        State('input_boolean.b0', 'on'),
        State('input_boolean.b1', 'on'),
        State('input_boolean.b2', 'on'),
    ]

    data = await RestoreStateData.async_get_instance(hass)
    await data.store.async_save(states)

    # Emulate a fresh load
    hass.data[DATA_RESTORE_STATE_TASK] = None

    state = await async_get_last_state(hass, 'input_boolean.b1')

    assert state is not None
    assert state.entity_id == 'input_boolean.b1'
    assert state.state == 'on'


async def test_load_error(hass):
    """Test that cache timeout returns none."""
    hass.state = CoreState.starting

    async def error_coro():
        raise HomeAssistantError()

    with patch('homeassistant.helpers.storage.Store.async_save',
               return_value=error_coro):
        state = await async_get_last_state(hass, 'input_boolean.b1')
    assert state is None
