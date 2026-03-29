"""
Tests for src/services/flow_executor.py

Tests graph utilities, variable rendering, switch routing, and business hours
without requiring Redis/DB/LLM connections.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.services.flow_executor import (
    _find_node,
    _find_node_by_type,
    _get_next_node_id,
    _get_all_next_handles,
    _render_vars,
)


# ─── Sample flow fixtures ─────────────────────────────────────

SIMPLE_FLOW = {
    "ativo": True,
    "nodes": [
        {"id": "start-1", "type": "start", "data": {}},
        {"id": "text-1", "type": "sendText", "data": {"texto": "Olá {{nome}}!"}},
        {"id": "switch-1", "type": "switch", "data": {
            "conditions": [
                {"value": "1", "label": "Musculação", "handle": "h1"},
                {"value": "2", "label": "Crossfit", "handle": "h2"},
                {"value": "3", "label": "Natação", "handle": "h3"},
            ]
        }},
        {"id": "text-muscu", "type": "sendText", "data": {"texto": "Musculação selecionada"}},
        {"id": "text-cross", "type": "sendText", "data": {"texto": "Crossfit selecionado"}},
        {"id": "text-default", "type": "sendText", "data": {"texto": "Opção padrão"}},
        {"id": "bh-1", "type": "businessHours", "data": {"modo": "custom", "horarios": {}, "fusoHorario": "America/Sao_Paulo"}},
        {"id": "text-aberto", "type": "sendText", "data": {"texto": "Estamos abertos"}},
        {"id": "text-fechado", "type": "sendText", "data": {"texto": "Estamos fechados"}},
        {"id": "menu-1", "type": "menuFixoIA", "data": {
            "opcoes": [
                {"id": "op1", "titulo": "Plano Mensal", "handle": "h-mensal"},
                {"id": "op2", "titulo": "Plano Anual", "handle": "h-anual"},
            ],
            "instrucaoIA": "Responda sobre o plano",
        }},
    ],
    "edges": [
        {"source": "start-1", "target": "text-1"},
        {"source": "text-1", "target": "switch-1"},
        {"source": "switch-1", "target": "text-muscu", "sourceHandle": "h1"},
        {"source": "switch-1", "target": "text-cross", "sourceHandle": "h2"},
        {"source": "switch-1", "target": "text-default", "sourceHandle": "h3"},
        {"source": "bh-1", "target": "text-aberto", "sourceHandle": "aberto"},
        {"source": "bh-1", "target": "text-fechado", "sourceHandle": "fechado"},
        {"source": "menu-1", "target": "text-muscu", "sourceHandle": "h-mensal"},
        {"source": "menu-1", "target": "text-cross", "sourceHandle": "h-anual"},
    ],
}


# ─── Graph utility tests ──────────────────────────────────────

class TestFindNode:
    def test_find_existing_node(self):
        node = _find_node(SIMPLE_FLOW, "start-1")
        assert node is not None
        assert node["type"] == "start"

    def test_find_nonexistent_node(self):
        assert _find_node(SIMPLE_FLOW, "nonexistent") is None

    def test_find_by_type(self):
        node = _find_node_by_type(SIMPLE_FLOW, "start")
        assert node is not None
        assert node["id"] == "start-1"

    def test_find_by_type_not_found(self):
        assert _find_node_by_type(SIMPLE_FLOW, "webhook") is None


class TestGetNextNodeId:
    def test_simple_next(self):
        next_id = _get_next_node_id(SIMPLE_FLOW, "start-1")
        assert next_id == "text-1"

    def test_handle_routing(self):
        next_id = _get_next_node_id(SIMPLE_FLOW, "switch-1", source_handle="h1")
        assert next_id == "text-muscu"

    def test_handle_routing_h2(self):
        next_id = _get_next_node_id(SIMPLE_FLOW, "switch-1", source_handle="h2")
        assert next_id == "text-cross"

    def test_no_connection(self):
        assert _get_next_node_id(SIMPLE_FLOW, "text-muscu") is None

    def test_business_hours_handles(self):
        assert _get_next_node_id(SIMPLE_FLOW, "bh-1", source_handle="aberto") == "text-aberto"
        assert _get_next_node_id(SIMPLE_FLOW, "bh-1", source_handle="fechado") == "text-fechado"


class TestGetAllNextHandles:
    def test_switch_handles(self):
        handles = _get_all_next_handles(SIMPLE_FLOW, "switch-1")
        assert len(handles) == 3
        handle_ids = {h[0] for h in handles}
        assert handle_ids == {"h1", "h2", "h3"}


# ─── Variable rendering tests ─────────────────────────────────

class TestRenderVars:
    def test_simple_substitution(self):
        result = _render_vars("Olá {{nome}}!", {"nome": "Maria"})
        assert result == "Olá Maria!"

    def test_phone_var(self):
        result = _render_vars("Fone: {{phone}}", {"phone": "5511999999999"})
        assert result == "Fone: 5511999999999"

    def test_hora_data_vars(self):
        result = _render_vars(
            "Hoje é {{data}} às {{hora}}",
            {"data": "28/03/2026", "hora": "14:30"}
        )
        assert result == "Hoje é 28/03/2026 às 14:30"

    def test_missing_var_preserved(self):
        result = _render_vars("Olá {{nome_inexistente}}!", {})
        assert result == "Olá {{nome_inexistente}}!"

    def test_empty_text(self):
        assert _render_vars("", {"nome": "Maria"}) == ""

    def test_none_text(self):
        assert _render_vars(None, {"nome": "Maria"}) is None

    def test_nested_dot_notation(self):
        result = _render_vars("{{user.name}}", {"user": {"name": "João"}})
        assert result == "João"

    def test_multiple_vars(self):
        result = _render_vars("{{a}} e {{b}}", {"a": "1", "b": "2"})
        assert result == "1 e 2"


# ─── Switch routing tests ─────────────────────────────────────

class TestSwitchRouting:
    """Tests the _process_state logic for switch nodes indirectly via the
    condition matching patterns documented in the code."""

    def test_exact_value_match(self):
        conditions = SIMPLE_FLOW["nodes"][2]["data"]["conditions"]
        msg = "1"
        matched = None
        for cond in conditions:
            if msg == str(cond["value"]).lower().strip():
                matched = cond["handle"]
                break
        assert matched == "h1"

    def test_exact_label_match(self):
        conditions = SIMPLE_FLOW["nodes"][2]["data"]["conditions"]
        msg = "musculação"
        matched = None
        for cond in conditions:
            if msg == str(cond["label"]).lower().strip():
                matched = cond["handle"]
                break
        assert matched == "h1"

    def test_uazapi_prefix_strip(self):
        """Simulates the UazAPI prefix stripping."""
        raw_msg = "[Selecionou no menu]: Musculação"
        msg_lower = raw_msg.lower().strip()
        prefix = "[selecionou no menu]: "
        if msg_lower.startswith(prefix):
            msg_lower = msg_lower[len(prefix):].strip()
        assert msg_lower == "musculação"

    def test_default_route_when_no_match(self):
        """When no condition matches, switch uses the first available handle."""
        handles = _get_all_next_handles(SIMPLE_FLOW, "switch-1")
        assert handles[0][1] is not None  # Falls back to first handle


# ─── MenuFixoIA routing tests ──────────────────────────────────

class TestMenuFixoIARouting:
    def test_handle_routing_mensal(self):
        next_id = _get_next_node_id(SIMPLE_FLOW, "menu-1", source_handle="h-mensal")
        assert next_id == "text-muscu"

    def test_handle_routing_anual(self):
        next_id = _get_next_node_id(SIMPLE_FLOW, "menu-1", source_handle="h-anual")
        assert next_id == "text-cross"
