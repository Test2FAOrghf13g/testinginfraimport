"""The tests for the Restore component."""
from unittest.mock import patch

from homeassistant.core import CoreState, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.restore_state import (
    _get_restore_state_store, async_get_last_state)


async def test_caching_data(hass):
    """Test that we cache data."""
    hass.state = CoreState.starting

    states = [
        State('input_boolean.b0', 'on'),
        State('input_boolean.b1', 'on'),
        State('input_boolean.b2', 'on'),
    ]

    store = _get_restore_state_store(hass)
    await store.async_save(states)

    state = await async_get_last_state(hass, 'input_boolean.b1')

    assert state is not None
    assert state.entity_id == 'input_boolean.b1'
    assert state.state == 'on'


async def test_hass_running(hass):
    """Test that cache cannot be accessed while hass is running."""
    states = [
        State('input_boolean.b0', 'on'),
        State('input_boolean.b1', 'on'),
        State('input_boolean.b2', 'on'),
    ]

    store = _get_restore_state_store(hass)
    await store.async_save(states)

    state = await async_get_last_state(hass, 'input_boolean.b1')
    assert state is None


async def test_load_error(hass):
    """Test that cache timeout returns none."""
    hass.state = CoreState.starting

    async def error_coro():
        raise HomeAssistantError()

    with patch('homeassistant.helpers.storage.Store.async_save',
               return_value=error_coro):
        state = await async_get_last_state(hass, 'input_boolean.b1')
    assert state is None
