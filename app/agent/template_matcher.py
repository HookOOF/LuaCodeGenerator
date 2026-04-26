"""Template matcher: recognizes common task patterns and returns pre-built Lua code.

Skips the entire LLM pipeline for well-known task types, producing
instant, correct results. Falls back to None when no pattern matches.
"""

from __future__ import annotations

import json
import re
import logging

logger = logging.getLogger(__name__)


class TemplateMatch:
    def __init__(self, code: str, pattern_name: str):
        self.code = code
        self.pattern_name = pattern_name


def try_match(prompt: str, json_ctx: dict | None) -> TemplateMatch | None:
    """Try to match the prompt against known patterns. Returns None if no match."""
    prompt_lower = prompt.lower().strip()

    matchers = [
        _match_get_last_element,
        _match_increment_counter,
        _match_square_number,
        _match_count_elements,
        _match_concat_fields,
        _match_sum_field,
        _match_check_contains,
    ]

    for matcher in matchers:
        result = matcher(prompt_lower, prompt, json_ctx)
        if result:
            logger.info("Template matched: %s", result.pattern_name)
            return result

    return None


def _find_var_path(json_ctx: dict | None, var_name: str) -> str | None:
    """Find the full path to a variable in the JSON context."""
    if not json_ctx or "wf" not in json_ctx:
        return None

    def _search(obj, path: str, target: str) -> str | None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == target:
                    return f"{path}.{k}"
                found = _search(v, f"{path}.{k}", target)
                if found:
                    return found
        return None

    wf = json_ctx["wf"]
    for section in ["vars", "initVariables"]:
        if section in wf:
            found = _search(wf[section], f"wf.{section}", var_name)
            if found:
                return found

    return None


def _match_get_last_element(prompt_lower: str, prompt: str, json_ctx: dict | None) -> TemplateMatch | None:
    """Match: 'get last element from list/array'"""
    patterns = [
        r'(?:получи|верни|достань|извлеки)\s+последн',
        r'(?:last|final)\s+(?:element|item|entry)',
        r'последний\s+элемент',
    ]
    if not any(re.search(p, prompt_lower) for p in patterns):
        return None

    if not json_ctx or "wf" not in json_ctx:
        return None

    wf = json_ctx["wf"]
    array_path = None

    def find_array(obj, path):
        nonlocal array_path
        if isinstance(obj, list) and array_path is None:
            array_path = path
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                find_array(v, f"{path}.{k}")

    for section in ["vars", "initVariables"]:
        if section in wf:
            find_array(wf[section], f"wf.{section}")
            if array_path:
                break

    if not array_path:
        return None

    code = f"return {array_path}[#{array_path}]"
    return TemplateMatch(code=code, pattern_name="get_last_element")


def _match_increment_counter(prompt_lower: str, prompt: str, json_ctx: dict | None) -> TemplateMatch | None:
    """Match: 'increment variable by 1'"""
    patterns = [
        r'увеличив\w*\s+(?:значение\s+)?(?:переменн\w+\s+)?(\w+)',
        r'increment\s+(\w+)',
        r'(\w+)\s*\+\s*1',
    ]

    var_name = None
    for p in patterns:
        m = re.search(p, prompt_lower)
        if m:
            var_name = m.group(1)
            break

    if not var_name:
        return None

    if json_ctx:
        path = _find_var_path(json_ctx, var_name)
        if path:
            return TemplateMatch(code=f"return {path} + 1", pattern_name="increment_counter")

    return TemplateMatch(code=f"return wf.vars.{var_name} + 1", pattern_name="increment_counter")


def _match_square_number(prompt_lower: str, prompt: str, json_ctx: dict | None) -> TemplateMatch | None:
    """Match: 'square of number N'"""
    patterns = [
        r'квадрат\w*\s+числа\s+(\d+)',
        r'square\s+(?:of\s+)?(\d+)',
    ]

    for p in patterns:
        m = re.search(p, prompt_lower)
        if m:
            n = m.group(1)
            return TemplateMatch(
                code=f"return {n} * {n}",
                pattern_name="square_number",
            )

    return None


def _match_count_elements(prompt_lower: str, prompt: str, json_ctx: dict | None) -> TemplateMatch | None:
    """Match: 'count elements where status == X'"""
    patterns = [
        r'(?:посчитай|подсчитай)\s+количество\s+элементов.*(?:статус|status)\s*(?:равен|==|=)\s*["\']?(\w+)',
        r'count\s+elements.*(?:status|where)\s*(?:==|=)\s*["\']?(\w+)',
    ]

    for p in patterns:
        m = re.search(p, prompt_lower)
        if m:
            status_val = m.group(1)
            if json_ctx:
                wf = json_ctx.get("wf", {})
                for section in ["vars", "initVariables"]:
                    data = wf.get(section, {})
                    for k, v in data.items():
                        if isinstance(v, list) and v and isinstance(v[0], dict) and "status" in v[0]:
                            code = (
                                f"local count = 0\n"
                                f"for _, item in ipairs(wf.{section}.{k}) do\n"
                                f'  if item.status == "{status_val}" then\n'
                                f"    count = count + 1\n"
                                f"  end\n"
                                f"end\n"
                                f"return count"
                            )
                            return TemplateMatch(code=code, pattern_name="count_by_status")
    return None


def _match_concat_fields(prompt_lower: str, prompt: str, json_ctx: dict | None) -> TemplateMatch | None:
    """Match: 'combine/concat FIO fields into one string'"""
    patterns = [
        r'(?:собери|объедини|склей)\s+(?:фио|ФИО|имя)',
        r'(?:combine|concat|join)\s+(?:name|fio)',
    ]

    if not any(re.search(p, prompt_lower) for p in patterns):
        return None

    if not json_ctx or "wf" not in json_ctx:
        return None

    wf = json_ctx["wf"]
    name_fields = []
    section = "vars"

    for s in ["vars", "initVariables"]:
        data = wf.get(s, {})
        for k in data:
            kl = k.lower()
            if any(n in kl for n in ["name", "lastname", "firstname", "middlename",
                                      "фамилия", "имя", "отчество"]):
                name_fields.append((s, k))
                section = s

    if len(name_fields) < 2:
        return None

    lines = ["local parts = {}"]
    for s, field in name_fields:
        lines.append(
            f'if wf.{s}.{field} and wf.{s}.{field} ~= "" then\n'
            f'  table.insert(parts, wf.{s}.{field})\n'
            f'end'
        )
    lines.append('return table.concat(parts, " ")')
    code = "\n".join(lines)
    return TemplateMatch(code=code, pattern_name="concat_name_fields")


def _match_sum_field(prompt_lower: str, prompt: str, json_ctx: dict | None) -> TemplateMatch | None:
    """Match: 'sum all values of field X'"""
    patterns = [
        r'(?:посчитай|подсчитай|вычисли)\s+сумм\w+\s+(?:всех\s+)?(?:значений\s+)?(?:поля\s+)?(\w+)',
        r'(?:sum|total)\s+(?:all\s+)?(?:values\s+of\s+)?(?:field\s+)?(\w+)',
    ]

    for p in patterns:
        m = re.search(p, prompt_lower)
        if m:
            field_name = m.group(1)
            if json_ctx:
                wf = json_ctx.get("wf", {})
                for section in ["vars", "initVariables"]:
                    data = wf.get(section, {})
                    for k, v in data.items():
                        if isinstance(v, list) and v and isinstance(v[0], dict) and field_name in v[0]:
                            code = (
                                f"local total = 0\n"
                                f"for _, item in ipairs(wf.{section}.{k}) do\n"
                                f"  local val = tonumber(item.{field_name}) or 0\n"
                                f"  total = total + val\n"
                                f"end\n"
                                f"return total"
                            )
                            return TemplateMatch(code=code, pattern_name="sum_field")
    return None


def _match_check_contains(prompt_lower: str, prompt: str, json_ctx: dict | None) -> TemplateMatch | None:
    """Match: 'check if value is in array'"""
    patterns = [
        r'(?:проверь|проверить)\s*,?\s*(?:содержится|есть)\s+ли\s+(?:значение|элемент)',
        r'(?:check|verify)\s+(?:if|whether)\s+(?:value|element)\s+(?:is\s+)?(?:in|contains)',
    ]

    if not any(re.search(p, prompt_lower) for p in patterns):
        return None

    if not json_ctx or "wf" not in json_ctx:
        return None

    wf = json_ctx["wf"]
    array_var = None
    search_var = None

    for section in ["vars", "initVariables"]:
        data = wf.get(section, {})
        for k, v in data.items():
            if isinstance(v, list) and not array_var:
                array_var = f"wf.{section}.{k}"
            elif isinstance(v, str) and not search_var:
                search_var = f"wf.{section}.{k}"

    if not array_var or not search_var:
        return None

    code = (
        f"local target = {search_var}\n"
        f"for _, v in ipairs({array_var}) do\n"
        f"  if v == target then\n"
        f"    return true\n"
        f"  end\n"
        f"end\n"
        f"return false"
    )
    return TemplateMatch(code=code, pattern_name="check_contains")
