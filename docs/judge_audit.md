# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend REPLAY, positive class = `FAIL`).

| Tiêu chí | n | κ | Precision | Recall | Confusion (tp/fp/fn/tn) | Fail rate quan sát → Rogan-Gladen | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | 24 / 4 / 6 / 66 | 0.28 → 0.30 | **PASS** | **dùng** (chỉ cho giọng văn, không chặn release) |
| helpful | 100 | 0.375 | 1.000 | **0.300** | 9 / 0 / 21 / 70 | 0.09 → 0.30 | **FAIL** (κ, R) | **loại** |

## ≥5 case audit thủ công

Tone (`judge_tone_public.csv`, 10 bất đồng) và helpful (`judge_helpful_public.csv`, 21 bất đồng, tất cả cùng một chiều human=FAIL, judge=PASS):

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em", thêm "nha": quá suồng sã với khách khiếu nại. Rubric thêm: *xưng hô phải là "LogiX / anh/chị"; "em/bạn", "nha/nhé" ⇒ FAIL*. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ…" | PASS | FAIL | Người | Cùng lỗi xưng hô ("bạn"). Judge đọc là thân thiện. Áp quy tắc xưng hô ở #1, kèm 1 ví dụ âm tính trong prompt judge. |
| 3 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ thấy "Dạ, vui lòng" mà bỏ qua câu ra lệnh. Rubric thêm: *câu mệnh lệnh / cấm khách liên hệ ⇒ FAIL dù có kính ngữ*. |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi". Rubric ghi rõ: *xin lỗi không bắt buộc; ngắn mà đủ ý và lịch sự ⇒ PASS*. |
| 5 | H-051 "…LogiX đã refund 90.000đ…" | FAIL | PASS | Người | CS LogiX cho dùng từ "refund". Rubric thêm whitelist thuật ngữ (refund, ship, COD). |
| 6 | H-070 "…đã hoàn 90.000đ cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Emoji cười trong ngữ cảnh khiếu nại. Rubric thêm: *emoji ⇒ FAIL*. |
| 7 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** (về tone thì không) | Note của người chấm: nhãn người sai vì đọc nhầm ticket. Nhưng đây là lỗi *nội dung*, không phải *giọng văn*, nên không thuộc tiêu chí tone. Hành động: sửa nhãn tone về PASS, đẩy lỗi nội dung sang grader code. Ghi vào changelog nhãn. |
| 8 | H-094 "Da, LogiX da hoan 40.000đ… xin loi…" (mất dấu) | PASS | FAIL | Người | Tiếng Việt không dấu (dịch máy). Rubric thêm: *thiếu dấu tiếng Việt ⇒ FAIL*. |
| 9 | HL-015 helpful: "đã hoàn 55.000đ cho đơn O-112" (ledger 40.000đ) | PASS | FAIL | Người | Judge không thấy ledger nên không thể biết số sai. Không sửa được bằng rubric: tiền phải chấm bằng code (`reply_matches_ledger`, FM-08). |
| 10 | HL-016/028/096 helpful: xin lỗi dài, số tiền sai ledger | PASS | FAIL | Người | Judge bị câu xin lỗi dài "mua" điểm (verbosity bias). 18/21 bất đồng helpful có note "ledger ghi …"; 3 còn lại là câu "Ok bạn, đơn … xử lý rồi nhé". |
| 11 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Không nói kết quả, không có số tiền, không bước tiếp theo. Rubric helpful (nếu làm lại): *phải nêu kết quả + số tiền/bước tiếp*. |

## Kết luận
- **tone_ok dùng được** (κ 0.757, P 0.857, R 0.80, cả ba đạt FLOORS), nhưng chỉ làm metric theo dõi chất lượng giọng văn, không chặn release. 6/10 bất đồng là judge bỏ sót lỗi xưng hô/emoji/mệnh lệnh (fn=6), nên cập nhật rubric theo #1–#8 rồi calibrate lại.
- **helpful bị loại**: recall 0.30 (fn = 21 / 30 FAIL thật), κ 0.375. Precision 1.0 không cứu được: judge gần như không bao giờ nói FAIL (9/100), nên tỉ lệ lỗi quan sát 0.09 trong khi thật là 0.30 (Rogan-Gladen cũng ra 0.30). Dùng judge này làm gate sẽ cho qua 70% câu trả lời tệ. Nguyên nhân chính trong ma trận nhầm lẫn: 21 fn, trong đó 18 là reply nói số tiền khác ledger. Judge chỉ đọc text, không đọc ledger, nên **về nguyên tắc không chấm được** tiêu chí này. Thay bằng grader code `ReplyMatchesLedger` (metric `reply_matches_ledger`, chặn).
- Quy tắc giữ nguyên: tiền và approval luôn chấm bằng code; judge chỉ dùng cho tiêu chí phi tiền đã qua FLOORS.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí). Rubric sửa xong phải đo lại trên một tập nhãn người mới (held-out), nếu không κ sẽ bị "học thuộc" theo các ví dụ audit ở trên.
