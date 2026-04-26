"""Tests for the Lua validator module."""

import shutil

import pytest

from app.agent.validator import validate_lua, _check_domain_rules, _strip_lua_strings_and_comments

HAS_LUA = shutil.which("lua5.4") is not None or shutil.which("luac") is not None or shutil.which("lua") is not None
skip_no_lua = pytest.mark.skipif(not HAS_LUA, reason="lua/luac not installed")


class TestDomainRules:
    def test_jsonpath_detected(self):
        errors = _check_domain_rules('local x = $.wf.vars.name')
        assert any("JsonPath" in e for e in errors)

    def test_jsonpath_bracket(self):
        errors = _check_domain_rules("local x = $['wf']")
        assert any("JsonPath" in e for e in errors)

    def test_forbidden_os(self):
        errors = _check_domain_rules("os.time()")
        assert any("os" in e for e in errors)

    def test_forbidden_io(self):
        errors = _check_domain_rules("io.read()")
        assert any("io" in e for e in errors)

    def test_forbidden_require(self):
        errors = _check_domain_rules('local json = require("json")')
        assert any("require" in e for e in errors)

    def test_print_detected(self):
        errors = _check_domain_rules("print(wf.vars.x)")
        assert any("print" in e for e in errors)

    def test_zero_index_detected(self):
        errors = _check_domain_rules("return items[0]")
        assert any("[0]" in e for e in errors)

    def test_valid_code_no_errors(self):
        code = """\
local result = _utils.array.new()
for _, item in ipairs(wf.vars.items) do
  table.insert(result, item.name)
end
return result"""
        errors = _check_domain_rules(code)
        assert errors == []

    def test_forbidden_in_string_ignored(self):
        code = 'return "use require() to import"'
        errors = _check_domain_rules(code)
        assert errors == []

    def test_forbidden_in_comment_ignored(self):
        code = "-- os.time() is not available\nreturn 42"
        errors = _check_domain_rules(code)
        assert errors == []


class TestStripStringsAndComments:
    def test_strips_string(self):
        result = _strip_lua_strings_and_comments('local x = "os.time()"')
        assert "os.time" not in result

    def test_strips_single_comment(self):
        result = _strip_lua_strings_and_comments("-- require('json')\nreturn 1")
        assert "require" not in result

    def test_preserves_code(self):
        result = _strip_lua_strings_and_comments("local x = wf.vars.name")
        assert "wf.vars.name" in result


@pytest.mark.asyncio(loop_scope="session")
class TestValidateLua:
    @skip_no_lua
    async def test_valid_code(self):
        result = await validate_lua("return 42")
        assert result.is_valid

    @skip_no_lua
    async def test_syntax_error(self):
        result = await validate_lua("return if end")
        assert not result.is_valid
        assert result.error is not None

    @skip_no_lua
    async def test_valid_complex(self):
        code = """\
local result = _utils.array.new()
for _, item in ipairs(wf.vars.items) do
  if item.active then
    table.insert(result, item)
  end
end
return result"""
        result = await validate_lua(code)
        assert result.is_valid

    async def test_domain_violation_no_lua_needed(self):
        result = await validate_lua("os.execute('rm -rf /')")
        assert not result.is_valid
        assert "os" in result.error
