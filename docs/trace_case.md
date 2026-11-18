# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi bạn 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `<shape> <claim>@<seed>`, run ID trong report |
| Triệu chứng | Grader nào fail; reply nói gì so với ledger ghi gì |
| Bước sai đầu tiên | Số thứ tự event + kind + trích payload (≤1 dòng) |
| Vì sao là bước *đầu tiên* | Các bước trước đó đúng ra sao (dẫn số event) |
| Failure mode | Mã FM-xx trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng claim@seed trên shape `fixed`: bước đó khác thế nào |
| Regression test | Tên test + grader/assert nào bắt được; đã thấy fail trên variant lỗi và pass trên `fixed` chưa |
| Chưa chắc chắn | Điều trace không chứng minh được |

## Case của tôi: `seeded_regression` C-002@11 (FM-03 ticket_trust)

Bối cảnh: ticket C-002 viết "Đơn giao trễ **5 ngày**, hoàn phí ship giúp", nhưng DB ghi O-202 chỉ trễ **2 ngày**. Trễ 2 ngày thì không có clause nào cho hoàn, nên nhãn là `denied`, `refund_vnd = 0`.

Trace (`python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11`):
```
 1 handoff         task check_applicable_policy, tools lookup_order/lookup_policy/compute_compensation
 2 investigator    order O-202, delay_days 2, shipping_fee_vnd 20000, status delivered
 3 model_override  {"delay_days": 5}
 4 quote           {"amount_vnd": 20000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"]}
 5 refund_history  {"refund_count": 0, "refunded_vnd": 0}
 6 reply           "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."
ledger refund_vnd 20000 (nhãn 0), refund_count 1 (nhãn 0), status resolved (nhãn denied)
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run ID `R-seeded_regression-C-002-s11`. Lỗi lặp lại ở cả 5 seed (11/22/33/44/55); baseline `swarm` cũng dính ở seed 55 (`R-swarm-C-002-s55`). |
| Triệu chứng | Grader Lab 8 FAIL `status resolved != denied`. Ledger ghi **20.000đ** (nhãn 0đ) và reply nói "đã hoàn 20.000đ". Reply khớp ledger, nhưng cả hai đều sai so với nhãn: công ty mất 20.000đ cho một claim không đủ điều kiện. |
| Bước sai đầu tiên | **Event 3 `model_override`** `{"delay_days": 5}`: agent ghi đè `delay_days` của DB (2) bằng số khách tự khai trong ticket (5). |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` giao đúng việc và đúng tool. Event 2 `investigator` đọc DB đúng (`delay_days: 2`). Cả hai giống hệt shape `fixed`. Event 4 `quote` (20000, SHIP-LATE-03) chỉ là hệ quả: tính đúng công thức nhưng trên dữ kiện đã bị đè. Event 6 `reply` sai theo. Sửa event 3 thì event 4 ra 0 và claim bị từ chối đúng. |
| Failure mode | **FM-03** ticket_trust (layer model/prompt). |
| Đối chứng | `fixed C-002@11`: 1 handoff → 2 investigator (`delay_days: 2`) → **3 quote `{"amount_vnd": 0, "reason": "no_entitlement"}`** → 4 reply "chưa đủ điều kiện hoàn". **Không có** event `model_override`; ledger 0, status denied, grader Lab 8 PASS. |
| Regression test | `src/tests/test_lab9_trace_case.py` (marker `student`, chạy trong CI): `test_lab9_trace_case_seeded_regression_is_caught` khẳng định có đúng một override tại event 3 và ledger ≠ nhãn; `test_lab9_trace_case_fixed_keeps_db_fact` khẳng định `fixed` không override, ledger = 0, status denied. Cả hai đã chạy xanh: assert override bắt được variant lỗi, và cùng assert đó im lặng trên `fixed`. Trong eval, metric step-level `db_fact_kept` và outcome `refund_amount_correct` sẽ bắt cùng lỗi này. |
| Chưa chắc chắn | (1) Trace chỉ cho thấy agent *đã* tin ticket, không cho thấy *vì sao* (ở `swarm` gốc là quy tắc `seed % 5 == 0` trong code, không phải suy luận của LLM thật). (2) Với LLM thật, tần suất override có thể khác 5/5 seed. (3) Biến thể `quiet_override` tin ticket mà **không** ghi event `model_override`: test dựa vào event sẽ bỏ lọt, chỉ assert trên ledger (`refund_amount_correct`) mới bắt được. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
