"""«Подключить Телеграм»: a small window for the helper who installs Vega (Ivan, 2026-11-14).

The blind person cannot see the code Telegram sends, so the sighted helper types the phone number and
the code here once, at install. Vega, already running, notices the saved login and starts reading
messages; after updates and restarts nothing has to be done again.
"""

import threading
from pathlib import Path

from . import __version__
from .telegram_link import SESSION_FILE, TelethonBackend, api_keys, protect


def run(config_dir: Path) -> int:
    import tkinter as tk
    from tkinter import messagebox

    keys = api_keys()
    root = tk.Tk()
    root.title("Подключить Телеграм к Веге")
    root.resizable(False, False)
    if keys is None:
        messagebox.showerror("Vega", "Телеграм в этой версии Веги не настроен.")
        root.destroy()
        return 2
    font = ("Segoe UI", 12)
    state = {"backend": None}

    tk.Label(root, font=font, justify="left", wraplength=460,
             text="1. Впишите номер телефона, к которому привязан Телеграм, и нажмите «Получить код».\n"
                  "2. Телеграм пришлёт код в сообщении (на телефон или в Телеграм на этом компьютере). "
                  "Впишите его и нажмите «Войти».").grid(row=0, column=0, columnspan=2, padx=12, pady=(12, 8), sticky="w")
    tk.Label(root, text="Номер:", font=font).grid(row=1, column=0, padx=12, sticky="e")
    phone = tk.Entry(root, font=font, width=24)
    phone.insert(0, "+380")
    phone.grid(row=1, column=1, padx=12, pady=4, sticky="w")
    tk.Label(root, text="Код:", font=font).grid(row=3, column=0, padx=12, sticky="e")
    code = tk.Entry(root, font=font, width=24, state="disabled")
    code.grid(row=3, column=1, padx=12, pady=4, sticky="w")
    password_label = tk.Label(root, text="Облачный пароль:", font=font)
    password = tk.Entry(root, font=font, width=24, show="•")
    status = tk.Label(root, text="", font=font, fg="#1a4d8f", wraplength=460, justify="left")
    status.grid(row=6, column=0, columnspan=2, padx=12, pady=8, sticky="w")

    def background(work, done):
        def go():
            try:
                result = work()
            except Exception as error:  # shown to the helper, never silent
                root.after(0, lambda: done(None, error))
                return
            root.after(0, lambda: done(result, None))
        threading.Thread(target=go, daemon=True).start()

    def get_code():
        number = "+" + "".join(char for char in phone.get() if char.isdigit())
        if len(number) < 11:
            status.config(text="Впишите номер полностью, с кодом страны, например +380501234567.", fg="#b00020")
            return
        status.config(text="Запрашиваю код…", fg="#1a4d8f")

        def work():
            if state["backend"] is None:
                state["backend"] = TelethonBackend(keys[0], keys[1], "", __version__)
            state["backend"].send_code(number)

        def done(_result, error):
            if error is not None:
                status.config(text="Код не пришёл: {}. Проверьте номер и интернет.".format(error), fg="#b00020")
                return
            code.config(state="normal")
            code.focus_set()
            enter.config(state="normal")
            status.config(text="Код отправлен. Найдите сообщение от Telegram с кодом и впишите его.", fg="#1a4d8f")
        background(work, done)

    def save_and_close():
        target = Path(config_dir) / SESSION_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(protect(state["backend"].session().encode("utf-8")))
        messagebox.showinfo("Vega", "Телеграм подключён. Вега будет читать новые сообщения вслух.")
        root.destroy()

    def sign_in():
        backend = state["backend"]
        if password.winfo_ismapped():
            value = password.get()
            background(lambda: backend.sign_in_password(value), after_sign_in)
        else:
            value = "".join(char for char in code.get() if char.isdigit())
            background(lambda: backend.sign_in(value), after_sign_in)
        status.config(text="Вхожу…", fg="#1a4d8f")

    def after_sign_in(result, error):
        if error is not None:
            status.config(text="Не получилось войти: {}".format(error), fg="#b00020")
        elif result == "ok":
            save_and_close()
        elif result == "password":
            password_label.grid(row=4, column=0, padx=12, sticky="e")
            password.grid(row=4, column=1, padx=12, pady=4, sticky="w")
            password.focus_set()
            status.config(text="На Телеграме стоит облачный пароль. Впишите его и нажмите «Войти».", fg="#1a4d8f")
        elif result == "bad_password":
            status.config(text="Пароль не подошёл. Проверьте раскладку и попробуйте ещё раз.", fg="#b00020")
        elif result == "expired":
            status.config(text="Код устарел. Нажмите «Получить код» ещё раз.", fg="#b00020")
        else:
            status.config(text="Код не подошёл. Проверьте цифры.", fg="#b00020")

    tk.Button(root, text="Получить код", font=font, command=get_code).grid(row=2, column=1, padx=12, pady=4, sticky="w")
    enter = tk.Button(root, text="Войти", font=font, command=sign_in, state="disabled")
    enter.grid(row=5, column=1, padx=12, pady=4, sticky="w")
    phone.focus_set()
    phone.icursor("end")
    root.mainloop()
    return 0
