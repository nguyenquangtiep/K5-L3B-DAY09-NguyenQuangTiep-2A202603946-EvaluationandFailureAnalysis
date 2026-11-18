# Judge audit

Chạy (trong `src/`): `python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 10` và
`python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 25`.
Judge là một bộ phân loại, lớp dương = **FAIL** (việc của judge là tìm lỗi). Judge ở chế độ replay: verdict lưu sẵn trong CSV.

| Tiêu chí | n | κ | Precision | Recall | Ma trận (tp/fp/fn/tn) | Tỉ lệ FAIL quan sát → hiệu chỉnh (Rogan-Gladen) | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | 24 / 4 / 6 / 66 | 0.28 → 0.30 | **Đạt** (exit 0) | **dùng**, chỉ cho tiêu chí giọng văn, không chặn release một mình |
| helpful | 100 | 0.375 | 1.000 | 0.300 | 9 / 0 / 21 / 70 | 0.09 → 0.30 | **Không đạt**: κ < 0.6, R < 0.7 (exit 1) | **loại**, không dùng làm gate |

## ≥5 case audit thủ công

Tone: cả 10 bất đồng. Helpful: đại diện 3 nhóm trong 21 bất đồng (tất cả đều judge PASS, người FAIL).

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / hành động sửa rubric |
|---|---|---|---|---|---|
| 1 | tone H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em", "nha" quá suồng sã với khách khiếu nại. **Rubric:** thêm quy tắc xưng hô "LogiX – anh/chị"; xưng "em/bạn", trợ từ "nha/nhé" → FAIL. Thêm H-008 làm ví dụ FAIL. |
| 2 | tone H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ… rồi nha." | PASS | FAIL | Người | Cùng lỗi xưng hô như #1. Judge thấy "Dạ" là chấm thân thiện. **Rubric:** "có 'Dạ' không đủ để PASS". |
| 3 | tone H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Giọng ra lệnh, gạt khách. Judge chỉ bắt từ khóa lịch sự. **Rubric:** thêm tiêu chí "không ra lệnh / không chặn khách liên hệ"; ví dụ FAIL. |
| 4 | tone H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Ngắn nhưng đủ ý và lễ phép; judge phạt vì thiếu xin lỗi. **Rubric:** ghi rõ "không bắt buộc xin lỗi khi yêu cầu đã được giải quyết". |
| 5 | tone H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | Người | Style guide CS LogiX cho phép từ "refund". **Rubric:** thêm danh sách từ tiếng Anh được phép (refund, ship, voucher). |
| 6 | tone H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người, nhưng **không phải lỗi giọng văn** | Lời văn lịch sự; cái sai là hứa ngoài kết quả hệ thống (gần FM-08). **Không** sửa tone rubric; chuyển sang grader code đối chiếu reply với ledger (metric FM-08 ở M3). Tách tiêu chí, đừng nhồi vào tone. |
| 7 | tone H-070 "…đã hoàn 90.000đ cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Emoji cười trong ngữ cảnh khiếu nại. **Rubric:** cấm emoji (hoặc chỉ cho phép danh sách trung tính). Có thể kiểm bằng regex code, rẻ và chắc hơn judge. |
| 8 | tone H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | **Judge**, nhưng lý do sai | Note ghi người đọc nhầm ticket → **sửa nhãn người**. Nhưng câu này lễ phép; nếu nó sai thì sai về nội dung (từ chối nhầm), không phải giọng văn. Judge phạt trúng vì lý do lệch tiêu chí. **Hành động:** sửa nhãn trong bản CSV tiếp theo (không sửa file public đang dùng để kiểm), và ghi trong rubric rằng tone không chấm đúng/sai của quyết định. |
| 9 | tone H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ…" | FAIL | PASS | Người (lỗi nhỏ) | Lặp "Dạ" do lỗi gõ, không thiếu lễ phép. **Rubric:** lỗi gõ nhỏ không làm FAIL tone. |
| 10 | tone H-094 "Da, LogiX da hoan 40.000đ… xin loi vi su bat tien." | PASS | FAIL | Người | Mất dấu tiếng Việt (dịch máy), không chuyên nghiệp. **Rubric:** "tiếng Việt không dấu → FAIL". |
| 11 | helpful HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | Người | **18/21** bất đồng helpful là kiểu này: reply nói sai số tiền so với ledger. Judge **không thấy ledger** nên không thể biết. Đây là FM-08 → chấm bằng code, không bằng judge. |
| 12 | helpful HL-016 / HL-028 / HL-098: xin lỗi dài lặp 2 lần, số tiền sai (ledger 35.000đ / 35.000đ / 90.000đ) | PASS | FAIL | Người | Thiên vị độ dài (verbosity bias): câu dài, nhiều xin lỗi được chấm "hữu ích" dù thông tin quan trọng nhất (số tiền) sai. **Rubric:** "hữu ích" = đúng số tiền + đúng trạng thái + bước tiếp theo; độ dài không cộng điểm. |
| 13 | helpful HL-047 / HL-091 / HL-097 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Mơ hồ: không nói hoàn hay từ chối, bao nhiêu tiền, khi nào về. **Rubric:** reply phải nêu kết quả cụ thể; thêm ví dụ FAIL. |

## Kết luận

- **tone_ok: dùng được.** Đạt cả 3 sàn (κ 0.757, P 0.857, R 0.8). Bất đồng còn lại có quy luật rõ: judge chấm theo từ khóa lịch sự ("Dạ", "vui lòng") và bỏ qua xưng hô suồng sã, giọng ra lệnh, emoji, mất dấu (6 fn); và phạt oan câu ngắn, từ "refund", lỗi gõ (4 fp, trong đó H-081 là nhãn người sai). Các sửa rubric ở trên nhắm vào đúng các nhóm này. Tone chỉ là metric **theo dõi**, không chặn release một mình.
- **helpful: loại, không được dùng làm gate.** Ma trận 9/0/21/70: precision 1.0 trông đẹp (khi judge nói FAIL thì đúng), nhưng **recall 0.3**: judge bỏ sót 21/30 reply không hữu ích; κ 0.375 dưới sàn 0.6. Tỉ lệ FAIL quan sát 9% so với tỉ lệ hiệu chỉnh Rogan-Gladen **30%**: dùng judge này sẽ báo chất lượng tốt gấp ~3 lần thực tế. Nguyên nhân gốc: 18/21 lỗi bỏ sót là reply nói **sai số tiền so với ledger**, thông tin judge không có trong đầu vào. Một gate dựa trên judge này sẽ cho qua đúng loại lỗi đắt nhất (FM-08). Thay bằng: (1) grader **code** so số tiền trong reply với ledger (metric FM-08, M3), (2) viết lại rubric helpful (nêu kết quả cụ thể, độ dài không cộng điểm) rồi calibrate lại trên nhãn mới trước khi cân nhắc dùng.
- **Nguyên tắc rút ra:** tiền và approval luôn chấm bằng code; judge chỉ dùng cho tiêu chí mà nó có đủ thông tin để chấm (giọng văn).
- **Rủi ro còn lại:** judge chỉ được kiểm trên 100 dòng replay công khai, cùng phân phối với chỗ ta đọc để sửa rubric, nên số liệu có thể lạc quan. Cần một bộ nhãn người **mới, held-out** (và ≥2 người gán để đo đồng thuận người–người) trước khi tin κ; mỗi lần đổi prompt hay model của judge phải calibrate lại. Nhãn người cũng có lỗi (H-081), nên cần quy trình review nhãn.
