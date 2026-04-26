#!/usr/bin/env bash
# LocalScript API — тестовые curl-запросы (все 8 задач из публичной выборки)
set -euo pipefail

BASE="http://localhost:18080"
T=60

ok=0
fail=0

run_test() {
    local name="$1"
    local prompt="$2"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "TEST: $name"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    local resp
    if ! resp=$(curl -s --max-time "$T" -X POST "$BASE/generate" \
        -H "Content-Type: application/json" \
        -d "$prompt" 2>&1); then
        echo "$resp"
        echo "=> FAIL (curl error, server unreachable?)"
        fail=$((fail + 1))
        echo ""
        return
    fi
    echo "$resp" | python3 -m json.tool 2>/dev/null || echo "$resp"
    if echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('code','')" 2>/dev/null; then
        echo "=> PASS"
        ok=$((ok + 1))
    else
        echo "=> FAIL (empty code)"
        fail=$((fail + 1))
    fi
    echo ""
}

# ── 1. Последний элемент массива ──────────────────────────────────
run_test "1. Последний элемент массива" \
    '{"prompt": "Из полученного списка email получи последний.\n{\"wf\":{\"vars\":{\"emails\":[\"user1@example.com\",\"user2@example.com\",\"user3@example.com\"]}}}"}'

# ── 2. Счетчик попыток ────────────────────────────────────────────
run_test "2. Счетчик попыток" \
    '{"prompt": "Увеличивай значение переменной try_count_n на каждой итерации\n{\"wf\":{\"vars\":{\"try_count_n\":3}}}"}'

# ── 3. Очистка значений в переменных ──────────────────────────────
run_test "3. Очистка полей (оставить только ID, ENTITY_ID, CALL)" \
    '{"prompt": "Для полученных данных из предыдущего REST запроса очисти значения переменных ID, ENTITY_ID, CALL\n{\"wf\":{\"vars\":{\"RESTbody\":{\"result\":[{\"ID\":123,\"ENTITY_ID\":456,\"CALL\":\"example_call_1\",\"OTHER_KEY_1\":\"value1\",\"OTHER_KEY_2\":\"value2\"},{\"ID\":789,\"ENTITY_ID\":101,\"CALL\":\"example_call_2\",\"EXTRA_KEY_1\":\"value3\",\"EXTRA_KEY_2\":\"value4\"}]}}}}"}'

# ── 4. Приведение времени к ISO 8601 ──────────────────────────────
run_test "4. Время YYYYMMDD+HHMMSS -> ISO 8601" \
    '{"prompt": "Преобразуй время из формата YYYYMMDD и HHMMSS в строку в формате ISO 8601.\n{\"wf\":{\"vars\":{\"json\":{\"IDOC\":{\"ZCDF_HEAD\":{\"DATUM\":\"20231015\",\"TIME\":\"153000\"}}}}}}"}'

# ── 5. Проверка типа данных (items -> array) ──────────────────────
run_test "5. Ensure items are always arrays" \
    '{"prompt": "Как преобразовать структуру данных так, чтобы все элементы items в ZCDF_PACKAGES всегда были представлены в виде массивов, даже если они изначально не являются массивами\n{\"wf\":{\"vars\":{\"json\":{\"IDOC\":{\"ZCDF_HEAD\":{\"ZCDF_PACKAGES\":[{\"items\":[{\"sku\":\"A\"},{\"sku\":\"B\"}]},{\"items\":{\"sku\":\"C\"}}]}}}}}}"}'

# ── 6. Фильтрация массива (Discount/Markdown) ────────────────────
run_test "6. Фильтрация по Discount/Markdown" \
    '{"prompt": "Отфильтруй элементы из массива, чтобы включить только те, у которых есть значения в полях Discount или Markdown.\n{\"wf\":{\"vars\":{\"parsedCsv\":[{\"SKU\":\"A001\",\"Discount\":\"10%\",\"Markdown\":\"\"},{\"SKU\":\"A002\",\"Discount\":\"\",\"Markdown\":\"5%\"},{\"SKU\":\"A003\",\"Discount\":null,\"Markdown\":null},{\"SKU\":\"A004\",\"Discount\":\"\",\"Markdown\":\"\"}]}}}"}'

# ── 7. Дополнение кода (квадрат числа) ────────────────────────────
run_test "7. Добавь переменную с квадратом числа" \
    '{"prompt": "Добавь переменную с квадратом числа 5"}'

# ── 8. Конвертация времени в Unix ─────────────────────────────────
run_test "8. ISO 8601 -> Unix timestamp" \
    '{"prompt": "Конвертируй время в переменной recallTime в unix-формат.\n{\"wf\":{\"initVariables\":{\"recallTime\":\"2023-10-15T15:30:00+00:00\"}}}"}'

# ── Итоги ─────────────────────────────────────────────────────────
echo "═══════════════════════════════════════"
echo "RESULTS: $ok passed, $fail failed (of 8)"
echo "═══════════════════════════════════════"

# ── 9. Тест чат-сессии с обратной связью ──────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "TEST: Chat session with feedback"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

SESSION_ID=$(curl -s --max-time "$T" -X POST "$BASE/chat/sessions" \
    -H "Content-Type: application/json" 2>&1 | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null) || true

if [ -z "$SESSION_ID" ]; then
    echo "=> FAIL (could not create chat session)"
else
    echo "Session: $SESSION_ID"

    echo ""
    echo ">> Message 1: initial request"
    curl -s --max-time "$T" -X POST "$BASE/chat/sessions/$SESSION_ID/messages" \
        -H "Content-Type: application/json" \
        -d '{"content": "Напиши функцию для подсчета суммы элементов массива numbers.\n{\"wf\":{\"vars\":{\"numbers\":[1,2,3,4,5]}}}"}' \
        | python3 -m json.tool 2>/dev/null || echo "(no valid JSON response)"

    echo ""
    echo ">> Message 2: feedback (add average)"
    curl -s --max-time "$T" -X POST "$BASE/chat/sessions/$SESSION_ID/messages" \
        -H "Content-Type: application/json" \
        -d '{"content": "Добавь ещё вычисление среднего значения и верни таблицу с sum и avg"}' \
        | python3 -m json.tool 2>/dev/null || echo "(no valid JSON response)"

    echo ""
    echo ">> Message history:"
    curl -s --max-time "$T" "$BASE/chat/sessions/$SESSION_ID/messages" | python3 -c "
import sys, json
msgs = json.load(sys.stdin)
for m in msgs:
    role = m['role'].upper()
    code = m.get('lua_code', '')
    valid = m.get('is_valid')
    print(f'  [{role}] {m[\"content\"][:100]}...')
    if code:
        print(f'    code: {code[:80]}...')
        print(f'    valid: {valid}')
    print()
" 2>/dev/null || echo "(could not fetch message history)"
fi
