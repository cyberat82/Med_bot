
from telegram.ext import ApplicationBuilder
from bot import setup_application

app = ApplicationBuilder().token("YOUR_BOT_TOKEN").build()
setup_application(app)
app.run_polling()
