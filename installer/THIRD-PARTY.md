# Сторонние компоненты установщика

Все бесплатные; build-windows.cmd скачивает первые три сам, остальные кладутся вручную в `third_party\`.

| Папка в third_party | Что это | Откуда | Лицензия |
|---|---|---|---|
| `vosk-model-small-ru-0.22` | Распознавание русской речи, 45 МБ, работает офлайн | https://alphacephei.com/vosk/models | Apache 2.0 |
| `piper\piper.exe` | Нейросетевой синтез речи, офлайн, естественный голос | https://github.com/rhasspy/piper/releases (piper_windows_amd64.zip) | MIT |
| `piper\ru_RU-irina-medium.onnx` (+ `.json`) | Русский голос «Ирина» для Piper, 60 МБ | https://huggingface.co/rhasspy/piper-voices (ru/ru_RU) | см. карточку голоса |
| `rhvoice\RHVoice-voice-Russian-Aleksandr.exe` | Русский голос Windows (SAPI) для Windows 7, где своего нет | https://rhvoice.org/ и https://github.com/RHVoice/RHVoice/releases | GPL/LGPL, голоса — по своим лицензиям |
| `nvda\nvdaControllerClient64.dll` | Чтобы помощник и NVDA не говорили одновременно | Архив NVDA Controller Client с https://www.nvaccess.org | LGPL 2.1 |

Другие голоса Piper: «denis», «dmitri», «ruslan» (мужские). Положите `.onnx` и `.onnx.json` в `piper\` — помощник выберет «irina» или «denis», иначе первый найденный.

Если Piper не запустится на конкретном компьютере (например, на старой Windows 7), помощник сам перейдёт на голос Windows и запишет причину в `%APPDATA%\VoiceAssist\last-error.log`.
