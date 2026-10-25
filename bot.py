import base64
import json
import os
import subprocess
from openai import OpenAI
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import config

client = OpenAI(base_url=config.ROUTER_BASE_URL, api_key=config.ROUTER_API_KEY)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")
SKILLS_JSON_PATH = os.path.join(BASE_DIR, "skills.json")

os.makedirs(PROMPTS_DIR, exist_ok=True)

# 1. Quản lý Skills động
def load_skills():
    if os.path.exists(SKILLS_JSON_PATH):
        try:
            with open(SKILLS_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"skills": []}

def save_skills(data):
    with open(SKILLS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_prompt_content(filename):
    path = os.path.join(PROMPTS_DIR, filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def save_prompt_content(filename, content):
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

# Bàn phím sinh tự động theo danh sách skill hiện có
def get_main_keyboard(is_admin=False):
    skills_data = load_skills()
    buttons = []
    row = []
    for skill in skills_data.get("skills", []):
        row.append(skill["button_title"])
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    # Nút tiện ích cố định
    buttons.append(["📌 Đổi Barem / Đáp án", "ℹ️ Hướng dẫn"])
    if is_admin:
        buttons.append(["🛠️ Quản trị Skill AI (Chat)"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

USER_MODES = {}
USER_RUBRICS = {}

# 2. Xử lý lệnh /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    is_admin = (user_id == config.ADMIN_ID)
    markup = get_main_keyboard(is_admin)

    msg = (
        "Chào Cô giáo! Em là Trợ lý Sư phạm Ngữ văn.\n\n"
        "Cô hãy chọn một chức năng ở bảng điều khiển bên dưới để làm việc nhé."
    )
    if is_admin:
        msg += "\n\n*(Chế độ Admin: Bạn có thể bấm '🛠️ Quản trị Skill AI (Chat)' để thêm/xóa/sửa skill bất kỳ qua hội thoại tự nhiên)*"
    await update.message.reply_text(msg, reply_markup=markup, parse_mode="Markdown")

# 3. Luồng xử lý tin nhắn
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text
    is_admin = (chat_id == config.ADMIN_ID)
    skills_data = load_skills()

    # --- CHẾ ĐỘ QUẢN TRỊ VIÊN: CHAT ĐỂ THÊM/XÓA/SỬA SKILL & MENU ---
    if is_admin and USER_MODES.get(chat_id) == "admin_architect":
        if text.lower() in ["thoát", "exit", "quay lại", "/cancel"]:
            USER_MODES[chat_id] = None
            await update.message.reply_text("✅ Đã thoát chế độ Quản trị Skill.", reply_markup=get_main_keyboard(is_admin))
            return

        status = await update.message.reply_text("🧠 Em đang suy nghĩ, cập nhật file cấu hình và viết prompt...")

        # Đọc toàn bộ ngữ cảnh hiện tại
        skills_summary = json.dumps(skills_data, ensure_ascii=False, indent=2)
        system_architect_prompt = f"""
Bạn là Kiến trúc sư Hệ thống AI kiêm Quản trị viên Bot Telegram.
Hiện tại danh sách kỹ năng và menu của bot được lưu trong file `skills.json` như sau:
{skills_summary}

Người dùng (Admin) vừa gửi yêu cầu sau:
"{text}"

Nhiệm vụ của bạn:
1. Phân tích xem yêu cầu là: THÊM SKILL MỚI, SỬA SKILL CŨ, XÓA SKILL, ĐỔI TÊN MENU, hay chỉ là câu hỏi trò chuyện.
2. Trả về DUY NHẤT một khối JSON (không thêm bất kỳ chữ dẫn dắt nào ngoài JSON) theo định dạng sau:
{{
  "action": "create" hoặc "update" hoặc "delete" hoặc "chat",
  "skill_id": "mã_skill_viết_liền_không_dấu",
  "button_title": "Icon + Tên hiển thị trên nút bấm Telegram (ví dụ: 📖 Soạn giáo án)",
  "type": "text" hoặc "vision",
  "instruction": "Câu hướng dẫn ngắn khi người dùng bấm vào nút",
  "prompt_file": "ten_file_persona.md",
  "prompt_content": "Toàn bộ nội dung prompt Markdown chi tiết chuyên sâu cho skill này (chỉ cần nếu action là create/update)",
  "reply_message": "Lời giải thích ngắn gọn, thân thiện bằng tiếng Việt cho Admin biết bạn đã làm những gì."
}}
Nếu action là "chat", chỉ cần trả về trường "reply_message".
"""
        try:
            res = client.chat.completions.create(
                model=config.TEXT_MODEL,
                messages=[{"role": "user", "content": system_architect_prompt}],
                temperature=0.2
            )
            raw_output = res.choices[0].message.content.strip()
            # Bóc tách JSON nếu AI bọc trong ```json
            if "```json" in raw_output:
                raw_output = raw_output.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_output:
                raw_output = raw_output.split("```")[1].split("```")[0].strip()

            data = json.loads(raw_output)
            action = data.get("action")
            reply_msg = data.get("reply_message", "Đã thực hiện xong.")

            if action in ["create", "update"]:
                skill_id = data.get("skill_id")
                prompt_file = data.get("prompt_file", f"{skill_id}_persona.md")
                
                # Lưu nội dung prompt .md
                if "prompt_content" in data and data["prompt_content"]:
                    save_prompt_content(prompt_file, data["prompt_content"])

                # Cập nhật danh sách skills trong JSON
                existing = [s for s in skills_data.get("skills", []) if s["id"] != skill_id]
                existing.append({
                    "id": skill_id,
                    "button_title": data.get("button_title", f"📌 {skill_id}"),
                    "prompt_file": prompt_file,
                    "type": data.get("type", "text"),
                    "instruction": data.get("instruction", "Mời nhập yêu cầu:")
                })
                skills_data["skills"] = existing
                save_skills(skills_data)

            elif action == "delete":
                skill_id = data.get("skill_id")
                target_skill = next((s for s in skills_data.get("skills", []) if s["id"] == skill_id), None)
                if target_skill:
                    prompt_path = os.path.join(PROMPTS_DIR, target_skill.get("prompt_file", ""))
                    if os.path.exists(prompt_path):
                        os.remove(prompt_path)
                skills_data["skills"] = [s for s in skills_data.get("skills", []) if s["id"] != skill_id]
                save_skills(skills_data)

            # Nút bấm tương tác sau khi sửa xong
            inline_kb = [
                [InlineKeyboardButton("🚀 Đẩy lên GitHub (Push Git)", callback_data="admin_git_push")],
                [InlineKeyboardButton("🚪 Thoát Quản Trị", callback_data="admin_exit")]
            ]
            try:
                await status.edit_text(
                    f"{reply_msg}\n\n*Menu bàn phím đã tự động cập nhật ngay lập tức.*",
                    reply_markup=InlineKeyboardMarkup(inline_kb),
                    parse_mode="Markdown"
                )
            except Exception:
                await status.edit_text(
                    f"{reply_msg}\n\nMenu bàn phím đã tự động cập nhật ngay lập tức.",
                    reply_markup=InlineKeyboardMarkup(inline_kb)
                )
        except Exception as e:
            await status.edit_text(f"❌ Có lỗi khi cập nhật: {str(e)}")
        return

    # --- CÁC NÚT ĐIỀU HƯỚNG CHUNG ---
    if text == "🛠️ Quản trị Skill AI (Chat)" and is_admin:
        USER_MODES[chat_id] = "admin_architect"
        await update.message.reply_text(
            "🛠️ **Bật chế độ Kiến trúc sư Skill (Chat trực tiếp)**\n\n"
            "Anh có thể nhắn bất kỳ yêu cầu nào bằng lời nói tự nhiên, ví dụ:\n"
            "• *Thêm skill Soạn giáo án theo CV 5512, icon là 📖*\n"
            "• *Thêm skill Luyện viết mở bài hay cho học sinh giỏi*\n"
            "• *Xóa skill Tạo Đề*\n"
            "• *Đổi nút Hỗ trợ chấm điểm thành Chấm bài thi THCS*\n"
            "• *Sửa luật chấm bài: trừ nặng hơn lỗi viết hoa tùy tiện*\n\n"
            "👉 Nhắn tin mô tả của anh vào đây (hoặc nhắn `Thoát` để trở lại Menu chính):",
            parse_mode="Markdown"
        )
        return

    if text == "📌 Đổi Barem / Đáp án":
        USER_MODES[chat_id] = "set_rubric"
        await update.message.reply_text("Cô vui lòng gửi văn bản nội dung Đề bài hoặc Barem chấm đợt này nhé.")
        return

    if text == "ℹ️ Hướng dẫn":
        await update.message.reply_text(
            "📖 **Hướng dẫn nhanh:**\n"
            "• Chọn một chức năng trên bàn phím bên dưới để bắt đầu làm việc.\n"
            "• Nếu chấm bài: Chọn chức năng chấm bài rồi chụp gửi ảnh bài viết tay.\n"
            "• Nếu cần đổi đề thi/đáp án: Bấm '📌 Đổi Barem / Đáp án'."
        )
        return

    # --- KIỂM TRA BẤM VÀO CÁC NÚT SKILL ĐỘNG ---
    matched_skill = next((s for s in skills_data.get("skills", []) if s["button_title"] == text), None)
    if matched_skill:
        USER_MODES[chat_id] = matched_skill["id"]
        await update.message.reply_text(
            f"✅ **Đã kích hoạt: {matched_skill['button_title']}**\n\n"
            f"{matched_skill.get('instruction', 'Mời cô nhập nội dung:')}",
            parse_mode="Markdown"
        )
        return

    # --- XỬ LÝ NỘI DUNG VĂN BẢN THEO CHẾ ĐỘ HIỆN TẠI ---
    current_mode = USER_MODES.get(chat_id)
    if current_mode == "set_rubric":
        USER_RUBRICS[chat_id] = text
        USER_MODES[chat_id] = None
        await update.message.reply_text("✅ Đã ghi nhận barem mới! Giờ Cô có thể chọn chức năng chấm bài để tiếp tục.")
        return

    # Xử lý skill dạng text thông thường
    current_skill = next((s for s in skills_data.get("skills", []) if s["id"] == current_mode), None)
    if current_skill and current_skill.get("type") == "text":
        msg = await update.message.reply_text("⏳ Em đang soạn thảo theo yêu cầu chuyên môn...")
        prompt_content = load_prompt_content(current_skill.get("prompt_file"))
        res = client.chat.completions.create(
            model=config.TEXT_MODEL,
            messages=[
                {"role": "system", "content": prompt_content},
                {"role": "user", "content": text}
            ]
        )
        await msg.edit_text(res.choices[0].message.content)
        return

    # Nhắc chọn menu nếu gõ tự do
    await update.message.reply_text(
        "Cô/Bạn vui lòng chọn một chức năng ở bảng điều khiển bên dưới.",
        reply_markup=get_main_keyboard(is_admin)
    )

# 4. Xử lý ảnh viết tay gửi lên (Vision)
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    skills_data = load_skills()
    current_mode = USER_MODES.get(chat_id)
    
    # Tìm skill vision đang chọn hoặc mặc định skill vision đầu tiên
    skill = next((s for s in skills_data.get("skills", []) if s["id"] == current_mode and s.get("type") == "vision"), None)
    if not skill:
        skill = next((s for s in skills_data.get("skills", []) if s.get("type") == "vision"), None)

    if not skill:
        await update.message.reply_text("Hiện chưa có kỹ năng đọc ảnh nào được cấu hình.")
        return

    status_msg = await update.message.reply_text(f"⏳ Em đang đọc chữ viết tay theo chuẩn '{skill['button_title']}'...")
    photo = await update.message.photo[-1].get_file()
    photo_bytes = await photo.download_as_bytearray()
    base64_image = base64.b64encode(photo_bytes).decode("utf-8")

    rubric = USER_RUBRICS.get(chat_id, "Barem chấm văn nghị luận chung.")
    user_prompt = f"Barem đợt chấm của cô:\n{rubric}\n\nHãy đọc và chấm bài viết tay sau:"
    prompt_content = load_prompt_content(skill.get("prompt_file"))

    try:
        res = client.chat.completions.create(
            model=config.VISION_MODEL,
            messages=[
                {"role": "system", "content": prompt_content},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            temperature=0.2
        )
        await status_msg.edit_text(res.choices[0].message.content)
    except Exception as e:
        await status_msg.edit_text(f"❌ Lỗi xử lý: {str(e)}")

# 5. Xử lý nút bấm Inline (Git Push & Thoát)
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if chat_id != config.ADMIN_ID:
        return

    if query.data == "admin_git_push":
        cmd = f'cd "{BASE_DIR}" && git add . && git commit -m "Auto-update skills via Admin Chat" && git push'
        run = subprocess.run(cmd, cwd=BASE_DIR, shell=True, capture_output=True, text=True)
        if run.returncode == 0:
            await query.message.reply_text("🚀 Đã sao lưu và đẩy các thay đổi lên GitHub thành công!")
        else:
            await query.message.reply_text(f"⚠️ Lỗi Git:\n`{run.stderr}`", parse_mode="Markdown")

    elif query.data == "admin_exit":
        USER_MODES[chat_id] = None
        await query.message.delete()
        await query.message.reply_text("✅ Đã thoát Quản trị.", reply_markup=get_main_keyboard(True))

if __name__ == "__main__":
    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    print("Bot Trợ Lý Văn (Dynamic Engine) đã sẵn sàng...")
    app.run_polling()
