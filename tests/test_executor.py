"""Tests for the Lua executor module."""

import shutil

import pytest

from app.agent.executor import (
    json_to_lua,
    extract_json_context,
    build_test_script,
    run_lua_with_tests,
)

HAS_LUA = shutil.which("lua5.4") is not None or shutil.which("lua") is not None
skip_no_lua = pytest.mark.skipif(not HAS_LUA, reason="lua5.4/lua not installed")


# --- json_to_lua ---

class TestJsonToLua:
    def test_nil(self):
        assert json_to_lua(None) == "nil"

    def test_bool_true(self):
        assert json_to_lua(True) == "true"

    def test_bool_false(self):
        assert json_to_lua(False) == "false"

    def test_integer(self):
        assert json_to_lua(42) == "42"

    def test_float(self):
        assert json_to_lua(3.14) == "3.14"

    def test_string(self):
        assert json_to_lua("hello") == '"hello"'

    def test_string_with_quotes(self):
        result = json_to_lua('say "hi"')
        assert '\\"' in result

    def test_string_with_newline(self):
        result = json_to_lua("line1\nline2")
        assert "\\n" in result

    def test_empty_list(self):
        assert json_to_lua([]) == "{}"

    def test_list(self):
        result = json_to_lua([1, 2, 3])
        assert result == "{1, 2, 3}"

    def test_empty_dict(self):
        assert json_to_lua({}) == "{}"

    def test_simple_dict(self):
        result = json_to_lua({"name": "Ivan", "age": 30})
        assert "name" in result
        assert "Ivan" in result
        assert "age" in result

    def test_identifier_keys_no_brackets(self):
        result = json_to_lua({"validKey": 1})
        assert "validKey = 1" in result

    def test_special_keys_use_brackets(self):
        result = json_to_lua({"key-with-dash": 1})
        assert '["key-with-dash"]' in result

    def test_nested(self):
        data = {"wf": {"vars": {"emails": ["a@b.com", "c@d.com"]}}}
        result = json_to_lua(data)
        assert "wf" in result
        assert "vars" in result
        assert "emails" in result


# --- extract_json_context ---

class TestExtractJsonContext:
    def test_simple(self):
        prompt = 'Get last email.\n{"wf":{"vars":{"emails":["a@b.com"]}}}'
        ctx = extract_json_context(prompt)
        assert ctx is not None
        assert "wf" in ctx
        assert "emails" in ctx["wf"]["vars"]

    def test_no_json(self):
        ctx = extract_json_context("Just do something simple")
        assert ctx is None

    def test_with_extra_text_after(self):
        prompt = 'Task here.\n{"wf":{"vars":{"x":1}}} and then more text'
        ctx = extract_json_context(prompt)
        assert ctx is not None
        assert ctx["wf"]["vars"]["x"] == 1


# --- build_test_script ---

class TestBuildTestScript:
    def test_contains_preamble(self):
        script = build_test_script("return 42", None, 'assert(_result == 42, "bad")')
        assert "_utils" in script
        assert "wf" in script

    def test_contains_code(self):
        script = build_test_script("return 42", None, "")
        assert "return 42" in script

    def test_contains_assertions(self):
        assertion = 'assert(_result == 42, "wrong")'
        script = build_test_script("return 42", None, assertion)
        assert assertion in script

    def test_with_json_context(self):
        ctx = {"wf": {"vars": {"x": 10}}}
        script = build_test_script("return wf.vars.x", ctx, "")
        assert "x = 10" in script

    def test_tests_passed_marker(self):
        script = build_test_script("return 1", None, "")
        assert "TESTS_PASSED" in script


# --- run_lua_with_tests (requires lua) ---

@pytest.mark.asyncio(loop_scope="session")
class TestRunLuaWithTests:
    @skip_no_lua
    async def test_simple_pass(self):
        result = await run_lua_with_tests("return 42", None, 'assert(_result == 42, "wrong")')
        assert result.success
        assert result.tests_passed

    @skip_no_lua
    async def test_simple_fail(self):
        result = await run_lua_with_tests("return 42", None, 'assert(_result == 99, "expected 99")')
        assert not result.success
        assert not result.tests_passed

    @skip_no_lua
    async def test_runtime_error(self):
        result = await run_lua_with_tests("error('boom')", None, "")
        assert not result.success
        assert "boom" in result.stderr or "boom" in result.error_summary

    @skip_no_lua
    async def test_with_context(self):
        ctx = {"wf": {"vars": {"emails": ["a@b.com", "c@d.com", "last@test.com"]}}}
        code = "return wf.vars.emails[#wf.vars.emails]"
        assertion = 'assert(_result == "last@test.com", "wrong email")'
        result = await run_lua_with_tests(code, ctx, assertion)
        assert result.success
        assert result.tests_passed

    @skip_no_lua
    async def test_timeout(self):
        result = await run_lua_with_tests("while true do end", None, "", timeout=1.0)
        assert not result.success
        assert "timed out" in result.error_summary.lower()
