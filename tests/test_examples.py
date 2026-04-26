"""Tests that run each public example's expected Lua code through the executor.

These tests verify that the reference code from the knowledge base actually works
when executed with the corresponding JSON context.
"""

import shutil

import pytest

from app.agent.executor import run_lua_with_tests

HAS_LUA = shutil.which("lua5.4") is not None or shutil.which("lua") is not None
skip_no_lua = pytest.mark.skipif(not HAS_LUA, reason="lua5.4/lua not installed")


REFERENCE_TESTS = [
    {
        "name": "last_email",
        "code": "return wf.vars.emails[#wf.vars.emails]",
        "context": {"wf": {"vars": {"emails": ["user1@example.com", "user2@example.com", "user3@example.com"]}}},
        "assertions": 'assert(_result == "user3@example.com", "expected user3, got: " .. tostring(_result))',
    },
    {
        "name": "try_count_increment",
        "code": "return wf.vars.try_count_n + 1",
        "context": {"wf": {"vars": {"try_count_n": 3}}},
        "assertions": 'assert(_result == 4, "expected 4, got: " .. tostring(_result))',
    },
    {
        "name": "clean_fields",
        "code": """\
result = wf.vars.RESTbody.result
for _, filteredEntry in pairs(result) do
  for key, value in pairs(filteredEntry) do
    if key ~= "ID" and key ~= "ENTITY_ID" and key ~= "CALL" then
      filteredEntry[key] = nil
    end
  end
end
return result""",
        "context": {
            "wf": {"vars": {"RESTbody": {"result": [
                {"ID": 123, "ENTITY_ID": 456, "CALL": "example_call_1", "OTHER_KEY_1": "value1"},
                {"ID": 789, "ENTITY_ID": 101, "CALL": "example_call_2", "EXTRA_KEY_1": "value3"},
            ]}}}
        },
        "assertions": "\n".join([
            'assert(type(_result) == "table", "expected table")',
            'assert(_result[1].ID == 123, "first ID should be 123")',
            'assert(_result[1].OTHER_KEY_1 == nil, "OTHER_KEY_1 should be removed")',
            'assert(_result[2].EXTRA_KEY_1 == nil, "EXTRA_KEY_1 should be removed")',
        ]),
    },
    {
        "name": "filter_discount_markdown",
        "code": """\
local result = _utils.array.new()
local items = wf.vars.parsedCsv
for _, item in ipairs(items) do
  if (item.Discount ~= "" and item.Discount ~= nil) or (item.Markdown ~= "" and item.Markdown ~= nil) then
    table.insert(result, item)
  end
end
return result""",
        "context": {
            "wf": {"vars": {"parsedCsv": [
                {"SKU": "A001", "Discount": "10%", "Markdown": ""},
                {"SKU": "A002", "Discount": "", "Markdown": "5%"},
                {"SKU": "A003", "Discount": None, "Markdown": None},
                {"SKU": "A004", "Discount": "", "Markdown": ""},
            ]}}
        },
        "assertions": "\n".join([
            'assert(type(_result) == "table", "expected table")',
            'assert(#_result == 2, "expected 2 items, got: " .. #_result)',
            'assert(_result[1].SKU == "A001", "first should be A001")',
            'assert(_result[2].SKU == "A002", "second should be A002")',
        ]),
    },
    {
        "name": "square_of_5",
        "code": "local n = tonumber('5')\nreturn n * n",
        "context": None,
        "assertions": 'assert(_result == 25, "expected 25, got: " .. tostring(_result))',
    },
    {
        "name": "sum_of_array",
        "code": """\
local total = 0
for _, order in ipairs(wf.vars.orders) do
  local amt = tonumber(order.amount) or 0
  total = total + amt
end
return total""",
        "context": {"wf": {"vars": {"orders": [{"id": 1, "amount": 150}, {"id": 2, "amount": 230}, {"id": 3, "amount": 80}]}}},
        "assertions": 'assert(_result == 460, "expected 460, got: " .. tostring(_result))',
    },
    {
        "name": "fio_concat",
        "code": """\
local parts = {}
if wf.vars.lastName and wf.vars.lastName ~= "" then
  table.insert(parts, wf.vars.lastName)
end
if wf.vars.firstName and wf.vars.firstName ~= "" then
  table.insert(parts, wf.vars.firstName)
end
if wf.vars.middleName and wf.vars.middleName ~= "" then
  table.insert(parts, wf.vars.middleName)
end
return table.concat(parts, " ")""",
        "context": {"wf": {"vars": {"lastName": "Иванов", "firstName": "Пётр", "middleName": "Сергеевич"}}},
        "assertions": 'assert(_result == "Иванов Пётр Сергеевич", "wrong FIO: " .. tostring(_result))',
    },
    {
        "name": "active_count",
        "code": """\
local count = 0
for _, user in ipairs(wf.vars.users) do
  if user.status == "active" then
    count = count + 1
  end
end
return count""",
        "context": {"wf": {"vars": {"users": [
            {"name": "A", "status": "active"},
            {"name": "B", "status": "inactive"},
            {"name": "C", "status": "active"},
        ]}}},
        "assertions": 'assert(_result == 2, "expected 2 active, got: " .. tostring(_result))',
    },
    {
        "name": "unique_values",
        "code": """\
local seen = {}
local result = _utils.array.new()
for _, client in ipairs(wf.vars.clients) do
  local city = client.city
  if city and not seen[city] then
    seen[city] = true
    table.insert(result, city)
  end
end
return result""",
        "context": {"wf": {"vars": {"clients": [
            {"name": "A", "city": "Москва"},
            {"name": "B", "city": "СПб"},
            {"name": "C", "city": "Москва"},
        ]}}},
        "assertions": "\n".join([
            'assert(#_result == 2, "expected 2 unique cities, got: " .. #_result)',
        ]),
    },
    {
        "name": "invert_boolean",
        "code": "return not wf.vars.isActive",
        "context": {"wf": {"vars": {"isActive": True}}},
        "assertions": 'assert(_result == false, "expected false, got: " .. tostring(_result))',
    },
    {
        "name": "domain_from_email",
        "code": """\
local email = wf.vars.email or ""
local domain = string.match(email, "@(.+)$")
return domain""",
        "context": {"wf": {"vars": {"email": "user@example.com"}}},
        "assertions": 'assert(_result == "example.com", "expected example.com, got: " .. tostring(_result))',
    },
    {
        "name": "word_count",
        "code": """\
local text = wf.vars.text or ""
local count = 0
for _ in string.gmatch(text, "%S+") do
  count = count + 1
end
return count""",
        "context": {"wf": {"vars": {"text": "Привет мир это тест"}}},
        "assertions": 'assert(_result == 4, "expected 4 words, got: " .. tostring(_result))',
    },
]


@pytest.mark.asyncio(loop_scope="session")
@skip_no_lua
@pytest.mark.parametrize(
    "test_case",
    REFERENCE_TESTS,
    ids=[t["name"] for t in REFERENCE_TESTS],
)
async def test_reference_code(test_case):
    result = await run_lua_with_tests(
        test_case["code"],
        test_case["context"],
        test_case["assertions"],
    )
    assert result.success, (
        f"Reference test '{test_case['name']}' failed:\n"
        f"  stdout: {result.stdout}\n"
        f"  stderr: {result.stderr}\n"
        f"  error: {result.error_summary}"
    )
