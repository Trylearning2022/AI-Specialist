"""Lớp bảo vệ an toàn thông tin cho đầu vào của người dùng (chạy TRƯỚC mọi xử lý, không gọi mô hình).

Định hướng nghiệp vụ bảo mật thông tin, cơ yếu, chứng thực số:
  1. Bí mật xác thực không được đưa vào hệ thống: khóa bí mật (PEM/PKCS#8), mã PIN, mật khẩu, cụm khôi phục.
     → Từ chối xử lý, KHÔNG lưu nội dung, nhắc người dùng thay đổi bí mật nếu đã lộ.
  2. Yêu cầu vượt qua, vô hiệu hóa cơ chế bảo mật, trích xuất khóa bí mật khỏi thiết bị.
     → Từ chối, chỉ dẫn quy trình chính thức (cấp lại, thu hồi qua bộ phận chứng thực số / cơ yếu).
  3. Nội dung mang dấu độ mật cao hơn cấp độ hệ thống được phép xử lý (SYSTEM_MAX_CLEARANCE).
     → Từ chối, nhắc quy định về xử lý tài liệu mật.

Kết quả được ghi kiểm toán (chỉ ghi LOẠI vi phạm, không ghi nội dung). Bổ sung mẫu nhận dạng tại các
biểu thức dưới đây (đánh dấu [TINH CHỈNH]) theo quy định của đơn vị.
"""
import re
from dataclasses import dataclass

from .config import get_settings
from .text import nfc

# [TINH CHỈNH] Mẫu nhận dạng bí mật xác thực
_PEM = re.compile(r"-----BEGIN (?:RSA |EC |DSA |ENCRYPTED |OPENSSH )?PRIVATE KEY-----", re.I)
_SECRET_VALUE = re.compile(
    r"\b(mã\s*pin|pin|puk|so\s*pin|mật\s*khẩu|mat\s*khau|password|passphrase|pass)\b\s*(?:của[^:\n]{0,30})?"
    r"\s*(?:là|:|=)\s*[\"“']?([^\s\"”',.;]{4,})", re.I)
_SEED = re.compile(r"\b(cụm từ khôi phục|seed phrase|recovery phrase)\b", re.I)
# [TINH CHỈNH] Yêu cầu vượt qua cơ chế bảo mật
_BYPASS = re.compile(
    r"\b(bẻ\s*khóa|bẻ\s*khoá|crack|hack|vượt\s*qua|qua\s*mặt|vô\s*hiệu\s*hóa|vô\s*hiệu\s*hoá|tắt|bỏ\s*qua|dò|đoán|"
    r"phá)\b[^.?!\n]{0,40}\b(xác\s*thực|mã\s*pin|mật\s*khẩu|chữ\s*ký\s*số|token|bảo\s*mật|tường\s*lửa|giám\s*sát|"
    r"kiểm\s*toán|mã\s*hóa|mã\s*hoá|chứng\s*thư)", re.I)
_EXTRACT_KEY = re.compile(
    r"\b(trích\s*xuất|lấy|sao\s*chép|xuất|copy|export|đọc)\b[^.?!\n]{0,30}\b(khóa\s*bí\s*mật|khoá\s*bí\s*mật|private\s*key)"
    r"[^.?!\n]{0,40}\b(token|thiết\s*bị|hsm|usb|thẻ)", re.I)
_LEGIT = re.compile(r"\b(quy\s*định|quy\s*trình|có\s*được\s*phép|cấm|xử\s*lý\s*thế\s*nào|khi\s*nào|trách\s*nhiệm|"
                    r"hình\s*thức\s*kỷ\s*luật|nguy\s*cơ|phòng\s*chống|phòng\s*ngừa|biện\s*pháp)\b", re.I)
# Dấu độ mật kiểu đóng dấu trên văn bản: một DÒNG RIÊNG chỉ gồm "MẬT" / "TỐI MẬT" / "TUYỆT MẬT" (chữ in hoa),
# hoặc trường "Độ mật: …". Câu hỏi thông thường ("tài liệu tối mật bảo quản thế nào?") không bị chặn.
_STAMP_LINE = re.compile(r"^\s*[\[(]?\s*(TUYỆT MẬT|TỐI MẬT|MẬT)\s*[\])]?\s*$", re.M)
_STAMP_FIELD = re.compile(r"độ\s*mật\s*[:：]\s*(tuyệt\s*mật|tối\s*mật|mật)\b", re.I)
_LEVEL = {"mật": 1, "tối mật": 2, "tuyệt mật": 3}


@dataclass
class GuardHit:
    kind: str      # bi_mat | vuot_bao_mat | do_mat
    message: str   # câu trả lời hiển thị cho người dùng


MSG_SECRET = (
    "**Không xử lý: nội dung có chứa bí mật xác thực** (khóa bí mật, mã PIN hoặc mật khẩu).\n\n"
    "Theo nguyên tắc bảo mật thông tin, bí mật xác thực chỉ do người được cấp quản lý, không nhập vào bất kỳ "
    "hệ thống hỏi đáp nào. Hệ thống **không lưu** nội dung câu hỏi này.\n\n"
    "- Nếu bí mật đã bị lộ: đề nghị đồng chí **đổi mã PIN/mật khẩu ngay** và báo cáo bộ phận quản lý chứng thực số "
    "để xem xét **thu hồi, cấp lại chứng thư số** theo quy định.\n"
    "- Hãy hỏi lại mà không kèm giá trị bí mật, ví dụ: “Quên mã PIN USB Token thì xử lý thế nào?”.")
MSG_BYPASS = (
    "**Không hỗ trợ yêu cầu này.** Hệ thống không hướng dẫn vượt qua, vô hiệu hóa cơ chế bảo mật hoặc trích xuất "
    "khóa bí mật khỏi thiết bị lưu khóa.\n\n"
    "Các trường hợp quên mã PIN, thiết bị bị khóa, cần sao lưu hoặc chuyển khóa đều phải thực hiện theo "
    "**quy trình chính thức** của bộ phận chứng thực số, cơ yếu (cấp lại thiết bị, thu hồi và cấp mới chứng thư số). "
    "Đồng chí có thể hỏi: “Quy trình cấp lại chứng thư số khi thiết bị bị khóa?”")
MSG_CLASSIFIED = (
    "**Không xử lý: nội dung mang dấu độ mật vượt cấp độ hệ thống được phép xử lý.**\n\n"
    "Tài liệu, thông tin mật chỉ được xử lý trên hệ thống, thiết bị đáp ứng yêu cầu bảo vệ bí mật nhà nước "
    "tương ứng. Hệ thống **không lưu** nội dung câu hỏi này; đề nghị đồng chí thực hiện theo quy định về "
    "bảo vệ bí mật của đơn vị.")


def stamp_level(text: str) -> int:
    """Độ mật cao nhất nhận diện được trong văn bản (0 = không thấy dấu độ mật)."""
    lv = 0
    for m in [*_STAMP_FIELD.finditer(text), *_STAMP_LINE.finditer(text)]:
        lv = max(lv, _LEVEL.get(re.sub(r"\s+", " ", m.group(1).lower()), 0))
    return lv


def check(text: str) -> GuardHit | None:
    """Kiểm tra đầu vào; None = cho phép xử lý."""
    if not get_settings().guard_enabled:
        return None
    t = nfc(text or "")
    if _PEM.search(t) or _SEED.search(t):
        return GuardHit("bi_mat", MSG_SECRET)
    m = _SECRET_VALUE.search(t)
    if m and not re.fullmatch(r"(gì|gi|bao\s*nhiêu|mặc\s*định|nào|như\s*thế\s*nào|sai|đúng)", m.group(2), re.I):
        # "mã PIN là gì", "mật khẩu mặc định" là câu hỏi hợp lệ; chỉ chặn khi có GIÁ TRỊ cụ thể
        if re.search(r"\d", m.group(2)) or len(m.group(2)) >= 6:
            return GuardHit("bi_mat", MSG_SECRET)
    if (_BYPASS.search(t) or _EXTRACT_KEY.search(t)) and not _LEGIT.search(t):
        return GuardHit("vuot_bao_mat", MSG_BYPASS)
    if stamp_level(t) > get_settings().system_max_clearance:
        return GuardHit("do_mat", MSG_CLASSIFIED)
    return None
