# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

## Case: `seeded_regression C-002@11`

Output (rút gọn):
```
== seeded_regression C-002@11  lab8 grader: FAIL (status resolved != denied)
   1 handoff            {... "task": "check_applicable_policy", "facts": {} ...}
   2 investigator       {"lookup_order": {"visible": true, "order": {"order_id": "O-202", "status": "delivered", "delay_days": 2 ...
   3 model_override     {"delay_days": 5}
   4 quote              {"amount_vnd": 20000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"] ...}
   5 refund_history     {"refund_count": 0, "refunded_vnd": 0}
   6 reply              {"text": "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."}
  refund_vnd     ledger=20000    label=0   <-- differs
  refund_count   ledger=1        label=0   <-- differs
  status         result=resolved label=denied
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11` (item E-002), report `E-seeded_regression-20261118-f6dc`, eval set `f6dcd4a6d54b` |
| Triệu chứng | `pass_rate` FAIL (`status resolved != denied`), `refund_amount_correct` FAIL (ledger 20000, nhãn 0), `db_fact_kept` FAIL. Reply "đã hoàn 20.000đ" khớp ledger nên FM-08 không bật. Reply trôi chảy và nhất quán, nhưng tiền đã ra sai. |
| Bước sai đầu tiên | **Event 3 `model_override`** `{"delay_days": 5}`: agent ghi đè `delay_days` của DB bằng số khách tự khai trong ticket ("giao trễ 5 ngày"). |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng contract (allowlist read-only, `facts: {}`). Event 2 `investigator` đọc đúng O-202 `delay_days=2`, `status=delivered`, tức là dữ liệu đúng đã nằm trong tay agent. Event 4 `quote` 20000 chỉ là hệ quả: clause SHIP-LATE-03 cần trễ ≥3 ngày, áp lên số 5 sai. |
| Failure mode | **FM-03** ticket_trust (`docs/failure_taxonomy.md`) |
| Đối chứng | `fixed C-002@11`: event 1–2 giống hệt, **không có event `model_override`**; event 3 `quote {"amount_vnd": 0, "reason": "no_entitlement"}`, event 4 reply "chưa đủ điều kiện hoàn". Ledger 0, status `denied`, lab8 PASS. Cùng claim trên `swarm` chỉ sai ở seed 55 (điểm yếu cố ý seed % 5 == 0), còn `seeded_regression` sai ở cả 5 seed. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_lab9_trace_case_regression_first_wrong_step_is_override` assert event 3 là `model_override`, `RefundAmountCorrect` = False, `DbFactKept` = False trên `seeded_regression`. `test_lab9_trace_case_fixed_keeps_db_fact` assert không có override, status `denied`, cả 3 grader đều True trên `fixed`. Đã chạy: cả hai xanh (fail-case bắt được lỗi trên variant lỗi, pass trên `fixed`). Item E-002 đã có sẵn trong eval set nên không thêm item mới với `provenance.from_trace`. |
| Chưa chắc chắn | Trace chỉ ghi *kết quả* override, không ghi *vì sao* agent chọn tin ticket (MockLLM không có reasoning). Biến thể `quiet_override` cho cùng lỗi mà không phát event `model_override`; khi đó `db_fact_kept` mù, chỉ còn `refund_amount_correct`/`pass_rate` ở mức outcome bắt được. Lỗi trên claim có ticket = DB (ví dụ C-001) không lộ ra. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
