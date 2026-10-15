# Pro Meeting — Phase 1 (Windows)

Pro Meeting thu tiếng nói trong phòng bằng micro Windows, tạo đoạn WAV đầu tiên 20 giây và các đoạn tiếp theo 90 giây, rồi hiện nguyên văn tiếng Nhật và bản dịch tiếng Việt. **Mặc định ứng dụng dùng Whisper Small + NLLB chạy cục bộ** để tránh thời gian chờ ChatGPT Web (trong 5 mẫu ~50 giây: 9,4–14,0 giây/đoạn với cấu hình 6 luồng; thử đoạn 90 giây: 18,2 giây). Các chế độ ChatGPT Web qua BrowserOS Neo vẫn có thể bật lại nếu cần đối chiếu độ chính xác.

## Chạy ứng dụng

**Nếu chọn dùng Google Chrome thông thường thay cho Neo**, cài extension một lần:

1. Mở Google Chrome, vào `chrome://extensions`, bật **Developer mode**.
2. Chọn **Load unpacked** → trỏ tới `C:\phong\AI\Voice\pro-meeting\extension`.
3. Giữ tài khoản đăng nhập ở `https://chatgpt.com` (cần quyền tải file âm thanh).

Mặc định khi **nhấp đúp `start.bat`**, ứng dụng nạp hai mô hình đã có trên máy (Whisper Small, NLLB 600M) rồi bắt đầu ghi âm. **Không cần mở Neo, đăng nhập ChatGPT, hay cài extension cho chế độ cục bộ.** Quá trình nạp mô hình ban đầu có thể mất hàng chục giây, không tính vào thời gian xử lý từng đoạn. Kết quả hiện trong cửa sổ Pro Meeting. Bấm **Dừng thu âm** để xử lý nốt các đoạn đã thu.

Chạy trực tiếp `.venv\Scripts\python.exe main.py` cũng chọn chế độ cục bộ, kể cả khi chưa đặt biến môi trường. Mọi đoạn thu chỉ được xử lý khi hai mô hình đã nạp xong.

**Chạy mặc định (nhanh, cục bộ) từ PowerShell:**

```powershell
$env:PRO_MEETING_BROWSER = 'neo'
$env:PRO_MEETING_ENGINE = 'local_fast'
.venv\Scripts\python.exe main.py
```

**Các chế độ xử lý:**

- `PRO_MEETING_ENGINE=local_fast` (mặc định với `PRO_MEETING_BROWSER=neo`): phiên âm Whisper Small trên CPU, dịch NLLB Nhật–Việt trên CPU. Không gửi dữ liệu âm thanh hoặc văn bản lên ChatGPT. Yêu cầu bộ trọng số `Systran/faster-whisper-small` và `facebook/nllb-200-distilled-600M` đã lưu trong Hugging Face cache của máy. Có thể chỉ định thư mục NLLB bằng `PRO_MEETING_NLLB_PATH`.
- Giới hạn mặc định 6 luồng CPU cho từng mô hình để giảm hiện tượng xử lý chậm đột biến trên Intel Core Ultra. Có thể thay bằng `PRO_MEETING_WHISPER_THREADS` và `PRO_MEETING_NLLB_THREADS` nếu cần thử máy khác. Thời gian dưới 30 giây được đo khi máy không quá tải, **không phải bảo đảm cứng** trên mọi trạng thái CPU.
- `PRO_MEETING_ENGINE=hybrid`: Whisper Small phiên âm cục bộ rồi GPT-6 **Instant** dịch văn bản qua Neo đã đăng nhập; thời gian xử lý tùy ChatGPT và có thể vượt 30 giây.
- `PRO_MEETING_ENGINE=web_audio`: gửi trực tiếp WAV lên GPT-6 Instant/Medium qua Neo đã đăng nhập. Chọn bằng `PRO_MEETING_CHATGPT_MODE=instant` hoặc `medium` (mặc định Instant). Neo MCP mặc định là `http://127.0.0.1:9010/mcp`. Đo 10 giây WAV: Instant từ 49,8–85,1 giây; Medium 81,4 giây; không đáp ứng SLA 30 giây.

Để dùng Neo ChatGPT Web, mở Neo đã đăng nhập và đặt:

```powershell
$env:PRO_MEETING_BROWSER = 'neo'
$env:PRO_MEETING_ENGINE = 'web_audio' # hoặc 'hybrid'
$env:PRO_MEETING_CHATGPT_MODE = 'instant'
.venv\Scripts\python.exe main.py
```

Để **dùng Google Chrome thông thường** với extension đã cài, đặt `$env:PRO_MEETING_BROWSER = 'chrome'` và `$env:PRO_MEETING_ENGINE = 'web_audio'` trước khi chạy.

Trong chế độ Chrome, extension đọc trạng thái Instant/Medium trong tab Pro Meeting. Ở Neo, app tự chọn mức Instant hoặc Medium. Những chỗ lời nói không rõ được hiển thị bằng `....`. Độ chính xác của Whisper Small + NLLB đối với các tên riêng và thuật ngữ Nhật–Việt có thể kém hơn ChatGPT Web; đo tốc độ thành công **không đồng nghĩa phiên âm hoặc dịch chính xác tuyệt đối**.

Nếu không tìm thấy profile có extension, app báo lỗi để bạn kiểm tra cài đặt ở `chrome://extensions`. Nếu đã cài extension trong nhiều profile hoặc muốn chỉ định cố định, đặt biến môi trường `PRO_MEETING_CHROME_PROFILE=Profile 3` (đổi `Profile 3` thành tên thư mục profile tương ứng). Việc cài extension là thao tác một lần do Chrome yêu cầu; app không thể lặng lẽ thêm một extension chưa được cấp quyền vào profile người dùng.

**Sau khi sửa các file trong `extension/`**, vào `chrome://extensions` và nhấn **Reload** trên Pro Meeting ChatGPT Bridge để Chrome nạp phiên bản mới. Extension tự làm mới tab ChatGPT riêng của nó nếu content script cũ bị mất sau khi Reload; không ảnh hưởng các tab ChatGPT cá nhân.

## Cách vận hành

```text
Windows microphone (mặc định) / speaker loopback (tuỳ chọn)
  → WAV mono PCM 16 kHz; micro: 20s đầu, sau đó 90s; loa: 20s
  → bounded queue (6 clips)
  → Whisper Small CPU → NLLB Nhật–Việt CPU (mặc định, local_fast)
    hoặc Whisper Small CPU → Neo ChatGPT Instant dịch (hybrid)
    hoặc Neo MCP / Chrome Bridge → Upload WAV → ChatGPT Web (web_audio)
  → Python UI (Tkinter): phiên âm gốc + tiếng Việt
```

**Không cần OpenAI API key, Playwright hoặc Chromium profile riêng.** Chế độ cục bộ không cần kết nối trình duyệt. Neo sử dụng phiên đăng nhập sẵn qua MCP; khi chọn Chrome, extension sử dụng Chrome profile đã cài sẵn và cổng `8796`.

## Cấu trúc

```text
start.bat                 Tự cài dependencies Python lần đầu và mở app
boot.py                   Báo lỗi khởi động trong Windows
main.py                   UI Tkinter
meeting/capture.py        WASAPI loopback, PCM WAV
meeting/pipeline.py       Hàng đợi và vòng đời thu/gửi
meeting/browser_bridge.py HTTP bridge, pin extension identity, audio chunks
meeting/neo_browser.py   Native WAV upload, gửi prompt và lấy phản hồi qua Neo MCP
meeting/local_asr.py     Whisper Small CPU, chống vòng lặp trong lời nói
meeting/local_translate.py  NLLB Nhật–Việt CPU, chia câu để tránh lặp
meeting/chatgpt_web.py    Adapter gửi tác vụ và đọc trả lời
extension/background.js   Extension poll bridge, quản lý tab sở hữu
extension/content.js      ChatGPT DOM, audio upload và quan sát trả lời
scripts/e2e_chatgpt.py   Test một file âm thanh với ChatGPT thật
scripts/e2e_neo_clips.py Test 5 file m4a, đo từng khâu trên cả 3 engine
```

## Kiểm tra

Kiểm tra local: `.venv\Scripts\python.exe -m unittest discover -s tests -v`.

Chạy thử 5 file m4a đầu tiên với engine cục bộ (tự chuyển WAV, xử lý tuần tự, xóa file WAV tạm; không cần Neo):

```powershell
$env:PRO_MEETING_BROWSER = 'neo'
$env:PRO_MEETING_ENGINE = 'local_fast'
$env:PYTHONIOENCODING = 'utf-8'
.venv\Scripts\python.exe scripts\e2e_neo_clips.py 'C:\Users\nothi\Documents\サウンド レコーディング\cut' --count 5
```

Sau khi cài extension và đăng nhập trong Chrome, để chạy thử một WAV có nội dung biết trước, **đóng Pro Meeting trước** (tránh trùng cổng bridge), sau đó chạy:

```powershell
.venv\Scripts\python.exe scripts\e2e_chatgpt.py "C:\path\to\sample.wav"
```

Script chỉ báo `PASSED` khi đã nhận được phản hồi có cả hai mục nguyên văn và dịch tiếng Việt. Cần đối chiếu nội dung phiên âm với nội dung mẫu vì mô hình có thể nghe sai.

## Đổi nguồn âm thanh

Mặc định: micro PC thu các đồng nghiệp đang nói trong phòng. Nếu tham gia Zoom/Teams từ chính PC và muốn thu tiếng phát ra loa, chạy bằng PowerShell:

```powershell
$env:PRO_MEETING_AUDIO_SOURCE = 'speakers'
.venv\Scripts\python.exe main.py
```

Nếu micro báo tín hiệu nhỏ, hãy kiểm tra thiết bị đầu vào, trạng thái tắt tiếng vật lý và âm lượng micro trong Windows. Pro Meeting chỉ tăng gain có giới hạn và không xoá đoạn chỉ vì micro quá nhỏ.
Nếu Windows/SoundCard báo gián đoạn dữ liệu thu (`data discontinuity`), ứng dụng hiển thị cảnh báo ở cuối đoạn; một số từ có thể bị mất dù vẫn có file WAV. Vấn đề driver/phần cứng này khác với việc loa không có tiếng.

## Giới hạn

- Các đoạn được xử lý **tuần tự**. Chế độ cục bộ phụ thuộc tải CPU và bộ nhớ; kết quả dưới 30 giây trong bài đo không bảo đảm cho mọi máy/trạng thái CPU. Whisper Small có thể nghe sai từ chuyên ngành/tên riêng, NLLB có thể dịch chưa sát. Dùng `hybrid` hoặc `web_audio` nếu ưu tiên độ chính xác và chấp nhận chờ lâu hơn.
- Chế độ **ChatGPT Web** phụ thuộc mạng và dịch vụ, có thể mất nhiều phút. Mặc định app đợi tối đa 15 phút (đặt `PRO_MEETING_CHAT_TIMEOUT_SECONDS` để thay đổi). Nếu kết quả gửi không chắc chắn hoặc giao diện ChatGPT thay đổi, ứng dụng dừng thay vì tự gửi lại đoạn có nguy cơ trùng.
- Mỗi phiên thu micro **hoặc** loa máy tính; chưa trộn đồng thời, chưa chia theo người nói hoặc xuất transcript ra file.
- File WAV tạm ở `%LOCALAPPDATA%\ProMeeting\chunks` và được xóa sau xử lý. Chế độ cục bộ không gửi dữ liệu; các chế độ ChatGPT Web gửi âm thanh/văn bản lên dịch vụ theo điều khoản tài khoản. Chỉ thu âm các cuộc họp bạn được phép ghi âm.

**Đối chiếu kiến trúc:** `pdf-ai/src/main/chrome-launcher.ts` dùng Chrome Windows mặc định và extension, `LamLongChart/examples/chatgpt-extension` dùng extension poll localhost, sở hữu tab ChatGPT. Pro Meeting áp dụng hai cơ chế đó cho file audio.
