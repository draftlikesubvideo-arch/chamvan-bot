import base64
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

# Đường dẫn thư mục
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")

def load_prompt(filename):
    path = os.path.join(PROMPTS_DIR, filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def save_prompt(filename, content):
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

# Bộ nhớ Prompt trong RAM
PROMPTS = {
    "grading": load_prompt("grading_persona.md"),
    "exam": load_prompt("exam_creator_persona.md"),
}

# Quản lý trạng thái
USER_MODES = {}
USER_RUBRICS = {}
ADMIN_EDITING_SKILL = {}

# Menu bàn phím
USER_KEYBOARD = [
    ["📝 Hỗ trợ chấm điểm", "📚 Hỗ trợ tạo đề"],
    ["📌 Đổi Barem / Đáp án", "ℹ️ Hướng dẫn"],
]
ADMIN_KEYBOARD = [
    ["📝 Hỗ trợ chấm điểm", "📚 Hỗ trợ tạo đề"],
    ["📌 Đổi Barem / Đáp án", "🛠️ Quản trị Skill AI"],
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    is_admin = (user_id == config.ADMIN_ID)
    
    markup = ReplyKeyboardMarkup(ADMIN_KEYBOARD if is_admin else USER_KEYBOARD, resize_keyboard=True)
    
    welcome = (
        "Chào Cô giáo! Em là Trợ lý Sư phạm Ngữ văn.\n\n"
        "Cô chọn chức năng ở bàn phím bên dưới để bắt đầu nhé:\n"
        "• 📝 **Hỗ trợ chấm điểm**: Chụp ảnh bài viết tay để nhận xét và gợi ý điểm.\n"
        "• 📚 **Hỗ trợ tạo đề**: Nhập yêu cầu để ra đề, ma trận và đáp án chi tiết."
    )
    if is_admin:
        welcome += "\n\n*(Chế độ Quản trị viên: Đã mở khóa menu chỉnh sửa Skill & Git)*"
        
    await update.message.reply_text(welcome, reply_markup=markup, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text
    is_admin = (chat_id == config.ADMIN_ID)

    # --- LUỒNG QUẢN TRỊ ADMIN (SỬA SKILL) ---
    if is_admin and chat_id in ADMIN_EDITING_SKILL:
        skill_target = ADMIN_EDITING_SKILL.pop(chat_id)
        status = await update.message.reply_text("⏳ Em đang phân tích yêu cầu và viết lại cấu trúc Prompt...")
        
        current_content = PROMPTS[skill_target]
        target_filename = "grading_persona.md" if skill_target == "grading" else "exam_creator_persona.md"
        
        # Nhờ LLM viết lại nội dung prompt
        edit_instruction = (
            f"Bạn là kiến trúc sư prompt AI. Dưới đây là nội dung prompt hiện tại của file `{target_filename}`:\n\n"
            f"```markdown\n{current_content}\n```\n\n"
            f"Người dùng muốn sửa đổi/bổ sung yêu cầu sau:\n\"{text}\"\n\n"
            f"Hãy viết lại toàn bộ nội dung file Markdown hoàn chỉnh nhất, giữ nguyên cấu trúc chuẩn và lồng ghép yêu cầu mới vào. "
            f"Chỉ trả về nội dung file markdown, không thêm lời dẫn."
        )
        
        res = client.chat.completions.create(
            model=config.TEXT_MODEL,
            messages=[{"role": "user", "content": edit_instruction}]
        )
        new_prompt_content = res.choices[0].message.content.strip("`markdown").strip("`").strip()
        
        # Lưu file và nạp lại RAM
        save_prompt(target_filename, new_prompt_content)
        PROMPTS[skill_target] = new_prompt_content
        
        # Nút bấm hành động Git
        inline_kb = [
            [InlineKeyboardButton("🚀 Đẩy lên GitHub & Nạp lại Bot", callback_data=f"git_push_{target_filename}")],
            [InlineKeyboardButton("👀 Xem Prompt vừa cập nhật", callback_data=f"view_prompt_{skill_target}")],
            [InlineKeyboardButton("❌ Đóng", callback_data="close_admin")]
        ]
        await status.edit_text(
            f"✅ **Đã ghi đè file `{target_filename}` và kích hoạt ngay vào RAM!**\n\n"
            f"Bạn có muốn đẩy bản cập nhật này lên GitHub không?",
            reply_markup=InlineKeyboardMarkup(inline_kb),
            parse_mode="Markdown"
        )
        return

    # --- LUỒNG MENU CHỨC NĂNG ---
    if text == "📝 Hỗ trợ chấm điểm":
        USER_MODES[chat_id] = "grading"
        rubric = USER_RUBRICS.get(chat_id, "Barem chung môn Văn.")
        await update.message.reply_text(
            f"✅ **Đã vào chế độ Chấm bài**\n📌 Barem hiện tại: _{rubric}_\n\n"
            "👉 Giờ Cô chỉ việc chụp hoặc gửi ảnh bài viết tay của học sinh vào đây!",
            parse_mode="Markdown"
        )

    elif text == "📚 Hỗ trợ tạo đề":
        USER_MODES[chat_id] = "exam"
        await update.message.reply_text(
            "✅ **Đã vào chế độ Tạo đề**\n\n"
            "Cô hãy nhắn thông tin đề cần soạn theo mẫu ngắn gọn, ví dụ:\n"
            "> *Lớp 9, Giữa kỳ 2, thời gian 90 phút, chủ đề Quê hương đất nước.*",
            parse_mode="Markdown"
        )

    elif text == "📌 Đổi Barem / Đáp án":
        USER_MODES[chat_id] = "set_rubric"
        await update.message.reply_text("Cô vui lòng gửi văn bản nội dung Đề bài hoặc Barem chấm đợt này nhé.")

    elif text == "🛠️ Quản trị Skill AI" and is_admin:
        inline_kb = [
            [InlineKeyboardButton("✏️ Sửa Skill Chấm Điểm", callback_data="edit_skill_grading")],
            [InlineKeyboardButton("✏️ Sửa Skill Tạo Đề", callback_data="edit_skill_exam")],
            [InlineKeyboardButton("🔄 Git Pull từ Repo về", callback_data="git_pull")]
        ]
        await update.message.reply_text(
            "🛠️ **Bảng điều khiển Quản trị Skill**\nChọn Skill bạn muốn yêu cầu AI viết lại:",
            reply_markup=InlineKeyboardMarkup(inline_kb),
            parse_mode="Markdown"
        )

    elif text == "ℹ️ Hướng dẫn":
        await update.message.reply_text(
            "📖 **Cách dùng:**\n"
            "1. Nhấn '📝 Hỗ trợ chấm điểm' rồi gửi ảnh bài làm học sinh.\n"
            "2. Nhấn '📌 Đổi Barem' khi chuyển sang tập bài thi khác.\n"
            "3. Nhấn '📚 Hỗ trợ tạo đề' khi muốn AI soạn đề mới."
        )

    else:
        mode = USER_MODES.get(chat_id)
        if mode == "set_rubric":
            USER_RUBRICS[chat_id] = text
            USER_MODES[chat_id] = "grading"
            await update.message.reply_text("✅ Đã ghi nhận barem mới! Giờ Cô có thể gửi ảnh bài làm để chấm.")
        elif mode == "exam":
            msg = await update.message.reply_text("⏳ Em đang soạn thảo đề và ma trận chuẩn GDPT...")
            res = client.chat.completions.create(
                model=config.TEXT_MODEL,
                messages=[
                    {"role": "system", "content": PROMPTS["exam"]},
                    {"role": "user", "content": text}
                ]
            )
            await msg.edit_text(res.choices[0].message.content)
        else:
            markup = ReplyKeyboardMarkup(ADMIN_KEYBOARD if is_admin else USER_KEYBOARD, resize_keyboard=True)
            await update.message.reply_text("Cô/Bạn vui lòng chọn một tác vụ trên menu.", reply_markup=markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if chat_id != config.ADMIN_ID:
        return

    if data == "edit_skill_grading":
        ADMIN_EDITING_SKILL[chat_id] = "grading"
        await query.message.reply_text(
            "📝 Hãy nhập yêu cầu bạn muốn thay đổi cho **Skill Chấm Điểm**:\n"
            "(Ví dụ: *Khắt khe hơn ở phần dẫn chứng thực tế, lỗi chính tả sai quá 3 từ trừ 0.5đ...*)"
        )

    elif data == "edit_skill_exam":
        ADMIN_EDITING_SKILL[chat_id] = "exam"
        await query.message.reply_text(
            "📚 Hãy nhập yêu cầu bạn muốn thay đổi cho **Skill Tạo Đề**:\n"
            "(Ví dụ: *Ưu tiên các đoạn trích Đọc hiểu thuộc thể loại thơ hiện đại, câu 2 viết nghị luận dạng so sánh...*)"
        )

    elif data.startswith("git_push_"):
        filename = data.replace("git_push_", "")
        cmd = f'cd "{BASE_DIR}" && git add . && git commit -m "Auto-update {filename} via Telegram" && git push'
        run = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if run.returncode == 0:
            await query.message.reply_text("🚀 Đã đẩy commit mới lên GitHub thành công!")
        else:
            await query.message.reply_text(f"⚠️ Git error:\n`{run.stderr}`", parse_mode="Markdown")

    elif data.startswith("view_prompt_"):
        target = data.replace("view_prompt_", "")
        content = PROMPTS[target]
        await query.message.reply_text(f"```markdown\n{content[:3800]}\n```", parse_mode="Markdown")

    elif data == "git_pull":
        cmd = f'cd "{BASE_DIR}" && git pull'
        run = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        # Nạp lại prompt sau khi pull
        PROMPTS["grading"] = load_prompt("grading_persona.md")
        PROMPTS["exam"] = load_prompt("exam_creator_persona.md")
        await query.message.reply_text(f"📥 Đã pull code mới nhất:\n`{run.stdout}`", parse_mode="Markdown")

    elif data == "close_admin":
        await query.message.delete()

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    status_msg = await update.message.reply_text("⏳ Em đang đọc chữ viết tay và đối chiếu barem...")

    photo = await update.message.photo[-1].get_file()
    photo_bytes = await photo.download_as_bytearray()
    base64_image = base64.b64encode(photo_bytes).decode("utf-8")

    rubric = USER_RUBRICS.get(chat_id, "Barem chấm văn nghị luận chung.")
    user_prompt = f"Barem đợt chấm của cô:\n{rubric}\n\nHãy đọc và chấm bài viết tay sau:"

    try:
        res = client.chat.completions.create(
            model=config.VISION_MODEL,
            messages=[
                {"role": "system", "content": PROMPTS["grading"]},
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

if __name__ == "__main__":
    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    print("Bot Văn đã sẵn sàng...")
    app.run_polling()
