; Installer texts in every language Vega speaks (Ivan, 2026-11-15). Each language is written the way
; people there say it, not word for word. %n is a new line. Saved as UTF-8 with BOM.
; Languages: ru Russian, uk Ukrainian, en_us English (United States), en_gb English (United Kingdom),
; de German, it Italian. The language list itself is in VoiceAssist.iss ([Languages]).

[LangOptions]
#ifdef LangEnUs
en_us.LanguageName=English (United States)
#endif
#ifdef LangEnGb
en_gb.LanguageName=English (United Kingdom)
#endif

[CustomMessages]
; ---------- Russian ----------
ru.UninstallName=Vega, голосовой помощник
ru.TaskAutostart=Запускать Вегу при входе в Windows (рекомендуется)
ru.TaskDesktop=Значок на рабочем столе
ru.IconManual=Инструкция Веги
ru.IconTelegram=Подключить Телеграм
ru.IconUninstall=Удалить Vega
ru.StatusVoice=Устанавливаю русский голос RHVoice…
ru.StatusChromeLink=Связываю Вегу с Chrome…
ru.RunVega=Запустить Вегу
ru.StatusTelegram=Открываю окно подключения Телеграма…
ru.StatusLanguage=Скачиваю голос и распознавание речи…
ru.KbNoFile=в установщике нет файла обновления
ru.KbStatus=Устанавливается обновление Windows KB3063858, нужное Веге. Это займёт пару минут...
ru.KbDenied=Windows не дала разрешение (%1)
ru.KbCode=код %1
ru.KbFailed=Не удалось установить обновление Windows KB3063858 (%1). Без него Вега на этой Windows 7 не запустится.%n%nЗапустите установку Веги ещё раз и разрешите изменения, когда Windows спросит.
ru.EditionTitle=Вариант Веги
ru.EditionSub=Обычная или с ИИ Gemini?
ru.EditionText=Обычная работает без интернета. С Gemini Вега лучше понимает неразборчивую речь и команды своими словами: фразы, которые она не поняла сама, отправляются в Google Gemini. Нужен интернет и бесплатный ключ Google.
ru.EditionStd=Обычная (без интернета)
ru.EditionGemini=С Gemini (лучше понимает, нужен ключ)
ru.WarnTitle=Важно: искусственный интеллект
ru.WarnSub=Прочитайте, пожалуйста, до конца
ru.WarnText=В версии «С Gemini» часть ответов даёт искусственный интеллект Google Gemini. Это программа, а не человек. Она может ошибаться, путать факты и говорить неправду уверенным голосом.%n%nНе принимайте только по её совету решения о здоровье, лекарствах, деньгах, документах и безопасности. Советуйтесь с врачом, близкими или специалистом.%n%nФразы из разговора с Gemini отправляются в Google. Не называйте пароли, номера карт и коды из СМС.%n%nРазработчик Веги не отвечает за ответы искусственного интеллекта и за последствия решений, принятых на их основе.
ru.WarnAgree=Я прочитал(а) и понимаю
ru.KeyTitle=Ключ Gemini
ru.KeySub=Как получить бесплатный ключ. Подробно: кнопка «Прочитать инструкцию» внизу
ru.KeyText=1. Нажмите кнопку «Открыть сайт Google» ниже и войдите в свой Google (почта Gmail и пароль).%n2. Если сайт спросит согласие с условиями, отметьте галочку и нажмите «Continue».%n3. Справа вверху нажмите «Create API key».%n4. В окне «Create a new key» имя не меняйте. В поле «Choose an imported project» выберите любой проект. Если список пуст, выберите «Create project», впишите Vega и нажмите «Create»: проект встанет в это поле.%n5. Нажмите «Create key». Откроется окно «API key details» с ключом (длинная строка). Нажмите внизу «Copy key».%n6. Вернитесь сюда, щёлкните в поле «Ключ» и нажмите Ctrl+V. Затем «Далее».
ru.KeyField=Ключ:
ru.KeySite=Открыть сайт Google
ru.KeyGuide=Прочитать инструкцию
ru.NameTitle=Имя пользователя
ru.NameSub=Как Веге вас называть?
ru.NameText=Необязательно. Если вписать имя, Вега будет здороваться по имени: «Привет, Игорь!» и иногда обращаться по имени в разговоре. Можно оставить пустым и потом сказать: «Вега, меня зовут Игорь».
ru.NameField=Имя:
ru.TgTitle=Телеграм
ru.TgSub=Подключить Телеграм к Веге?
ru.TgText=Вега будет читать вслух новые сообщения из Телеграма и отправлять сообщения голосом. Впишите номер телефона, к которому привязан Телеграм. После установки откроется окошко: Телеграм пришлёт код в сообщении, впишите его туда. Подключить можно и потом: ярлык «Vega» на рабочем столе.
ru.TgField=Номер телефона, с кодом страны:
ru.TgBox=Подключить Телеграм
ru.TgPrefix=+380
ru.ErrPhone=Впишите номер телефона полностью, с кодом страны, например +380501234567. Или снимите галочку «Подключить Телеграм», чтобы подключить потом.
ru.ErrWarn=Поставьте галочку «Я прочитал(а) и понимаю» или вернитесь назад и выберите обычную Вегу.
ru.ErrKeyEmpty=Вставьте ключ в поле «Ключ» (Ctrl+V) или вернитесь назад и выберите обычную Вегу.
ru.ErrKeyChars=В ключе не должно быть пробелов и кавычек. Скопируйте его ещё раз кнопкой «Copy key».
ru.ErrKeyPrefix=Обычно ключ начинается с AQ. или AIza. Всё равно использовать этот?
ru.ChromeStatus=Скачивается и устанавливается Google Chrome. Это может занять несколько минут...
ru.ChromeFailed=Google Chrome установить не удалось (нет интернета или Google не дал установщик). Vega работает и без него; Chrome можно поставить позже и запустить установщик Vega ещё раз.

#ifdef LangUk
; ---------- Ukrainian ----------
uk.UninstallName=Vega, голосовий помічник
uk.TaskAutostart=Запускати Вегу під час входу в Windows (рекомендовано)
uk.TaskDesktop=Значок на робочому столі
uk.IconManual=Інструкція Веги
uk.IconTelegram=Підключити Телеграм
uk.IconUninstall=Видалити Vega
uk.StatusVoice=Встановлюю голос RHVoice…
uk.StatusChromeLink=Пов'язую Вегу з Chrome…
uk.RunVega=Запустити Вегу
uk.StatusTelegram=Відкриваю вікно підключення Телеграму…
uk.StatusLanguage=Завантажую голос і розпізнавання мовлення… Це може тривати кілька хвилин.
uk.KbNoFile=в інсталяторі немає файлу оновлення
uk.KbStatus=Встановлюється оновлення Windows KB3063858, потрібне Везі. Це триватиме кілька хвилин...
uk.KbDenied=Windows не надала дозволу (%1)
uk.KbCode=код %1
uk.KbFailed=Не вдалося встановити оновлення Windows KB3063858 (%1). Без нього Вега на цій Windows 7 не запуститься.%n%nЗапустіть встановлення Веги ще раз і дозвольте зміни, коли Windows запитає.
uk.EditionTitle=Варіант Веги
uk.EditionSub=Звичайна чи зі штучним інтелектом Gemini?
uk.EditionText=Звичайна працює без інтернету. З Gemini Вега краще розуміє нерозбірливе мовлення і команди своїми словами: фрази, які вона не зрозуміла сама, надсилаються до Google Gemini. Потрібні інтернет і безкоштовний ключ Google.
uk.EditionStd=Звичайна (без інтернету)
uk.EditionGemini=З Gemini (краще розуміє, потрібен ключ)
uk.WarnTitle=Важливо: штучний інтелект
uk.WarnSub=Прочитайте, будь ласка, до кінця
uk.WarnText=У версії «З Gemini» частину відповідей дає штучний інтелект Google Gemini. Це програма, а не людина. Вона може помилятися, плутати факти й упевнено казати неправду.%n%nНе ухвалюйте лише за її порадою рішень щодо здоров'я, ліків, грошей, документів і безпеки. Радьтеся з лікарем, рідними або фахівцем.%n%nФрази з розмови з Gemini надсилаються до Google. Не називайте паролів, номерів карток і кодів із СМС.%n%nРозробник Веги не відповідає за відповіді штучного інтелекту та за наслідки рішень, ухвалених на їхній основі.
uk.WarnAgree=Я прочитав(ла) і розумію
uk.KeyTitle=Ключ Gemini
uk.KeySub=Як отримати безкоштовний ключ. Докладно: кнопка «Прочитати інструкцію» внизу
uk.KeyText=1. Натисніть кнопку «Відкрити сайт Google» нижче й увійдіть у свій Google (пошта Gmail і пароль).%n2. Якщо сайт попросить погодитися з умовами, поставте позначку й натисніть «Continue».%n3. Праворуч угорі натисніть «Create API key».%n4. У вікні «Create a new key» назву не змінюйте. У полі «Choose an imported project» виберіть будь-який проєкт. Якщо список порожній, виберіть «Create project», впишіть Vega і натисніть «Create»: проєкт з'явиться в цьому полі.%n5. Натисніть «Create key». Відкриється вікно «API key details» із ключем (довгий рядок). Натисніть унизу «Copy key».%n6. Поверніться сюди, клацніть у полі «Ключ» і натисніть Ctrl+V. Потім «Далі».
uk.KeyField=Ключ:
uk.KeySite=Відкрити сайт Google
uk.KeyGuide=Прочитати інструкцію
uk.NameTitle=Ім'я користувача
uk.NameSub=Як Везі до вас звертатися?
uk.NameText=Необов'язково. Якщо вписати ім'я, Вега вітатиметься на ім'я: «Привіт, Ігорю!» і часом звертатиметься на ім'я в розмові. Можна залишити порожнім і потім сказати: «Вего, мене звати Ігор».
uk.NameField=Ім'я:
uk.TgTitle=Телеграм
uk.TgSub=Підключити Телеграм до Веги?
uk.TgText=Вега читатиме вголос нові повідомлення з Телеграму й надсилатиме повідомлення голосом. Впишіть номер телефону, до якого прив'язаний Телеграм. Після встановлення відкриється віконце: Телеграм надішле код у повідомленні, впишіть його туди. Підключити можна й пізніше: ярлик «Vega» на робочому столі.
uk.TgField=Номер телефону з кодом країни:
uk.TgBox=Підключити Телеграм
uk.TgPrefix=+380
uk.ErrPhone=Впишіть номер телефону повністю, з кодом країни, наприклад +380501234567. Або зніміть позначку «Підключити Телеграм», щоб підключити пізніше.
uk.ErrWarn=Поставте позначку «Я прочитав(ла) і розумію» або поверніться назад і виберіть звичайну Вегу.
uk.ErrKeyEmpty=Вставте ключ у поле «Ключ» (Ctrl+V) або поверніться назад і виберіть звичайну Вегу.
uk.ErrKeyChars=У ключі не має бути пробілів і лапок. Скопіюйте його ще раз кнопкою «Copy key».
uk.ErrKeyPrefix=Зазвичай ключ починається з AQ. або AIza. Усе одно використати цей?
uk.ChromeStatus=Завантажується і встановлюється Google Chrome. Це може тривати кілька хвилин...
uk.ChromeFailed=Не вдалося встановити Google Chrome (немає інтернету або Google не надав інсталятор). Vega працює і без нього; Chrome можна встановити пізніше й запустити інсталятор Vega ще раз.
#endif

#ifdef LangEnUs
; ---------- English (United States) ----------
en_us.UninstallName=Vega voice assistant
en_us.TaskAutostart=Start Vega when I sign in to Windows (recommended)
en_us.TaskDesktop=Desktop shortcut
en_us.IconManual=Vega User Guide
en_us.IconTelegram=Connect Telegram
en_us.IconUninstall=Uninstall Vega
en_us.StatusVoice=Installing the RHVoice voice…
en_us.StatusChromeLink=Connecting Vega to Chrome…
en_us.RunVega=Start Vega
en_us.StatusTelegram=Opening the Telegram sign-in window…
en_us.StatusLanguage=Downloading the voice and speech recognition… This may take a few minutes.
en_us.KbNoFile=the update file is missing from the installer
en_us.KbStatus=Installing Windows update KB3063858, which Vega needs. This will take a couple of minutes...
en_us.KbDenied=Windows did not give permission (%1)
en_us.KbCode=code %1
en_us.KbFailed=Windows update KB3063858 could not be installed (%1). Without it, Vega won't start on this Windows 7 computer.%n%nRun the Vega installer again and allow the changes when Windows asks.
en_us.EditionTitle=Choose your version of Vega
en_us.EditionSub=Standard, or with Gemini AI?
en_us.EditionText=Standard works without the internet. With Gemini, Vega is better at understanding unclear speech and commands in your own words: anything she didn't understand is sent to Google Gemini. This needs the internet and a free Google key.
en_us.EditionStd=Standard (no internet needed)
en_us.EditionGemini=With Gemini (understands more, needs a key)
en_us.WarnTitle=Important: artificial intelligence
en_us.WarnSub=Please read this all the way through
en_us.WarnText=In the Gemini version, some answers come from Google Gemini, an artificial intelligence. It is a computer program, not a person. It can make mistakes, mix up facts, and say things that are wrong while sounding completely sure.%n%nDon't rely on its advice alone for decisions about your health, medications, money, documents, or safety. Talk to a doctor, your family, or a professional.%n%nWhat you say in a conversation with Gemini is sent to Google. Never say passwords, card numbers, or codes from text messages.%n%nThe developer of Vega is not responsible for the AI's answers or for any decisions made based on them.
en_us.WarnAgree=I have read and understand this
en_us.KeyTitle=Gemini key
en_us.KeySub=How to get a free key. For step-by-step help, click "Read the guide" below
en_us.KeyText=1. Click "Open Google website" below and sign in to your Google account (your Gmail address and password).%n2. If the site asks you to accept the terms, check the box and click "Continue".%n3. In the top right corner, click "Create API key".%n4. In the "Create a new key" window, leave the name as it is. Under "Choose an imported project", pick any project. If the list is empty, choose "Create project", type Vega, and click "Create": the project will appear in that box.%n5. Click "Create key". The "API key details" window opens with your key (a long line of letters and numbers). Click "Copy key" at the bottom.%n6. Come back here, click in the "Key" box, and press Ctrl+V. Then click "Next".
en_us.KeyField=Key:
en_us.KeySite=Open Google website
en_us.KeyGuide=Read the guide
en_us.NameTitle=Your name
en_us.NameSub=What should Vega call you?
en_us.NameText=Optional. If you type your name, Vega will greet you by name, "Hi, John!", and sometimes use it when she talks to you. You can leave this blank and say later: "Vega, my name is John".
en_us.NameField=Name:
en_us.TgTitle=Telegram
en_us.TgSub=Connect Telegram to Vega?
en_us.TgText=Vega will read your new Telegram messages out loud and send messages for you by voice. Type the phone number your Telegram account uses. After setup, a small window opens: Telegram will send you a code in a message, type it there. You can also do this later with the "Vega" shortcut on the desktop.
en_us.TgField=Phone number, with country code:
en_us.TgBox=Connect Telegram
en_us.TgPrefix=+1
en_us.ErrPhone=Please type the full phone number with the country code, for example +12025550123. Or uncheck "Connect Telegram" to do it later.
en_us.ErrWarn=Check the box "I have read and understand this", or go back and choose Standard Vega.
en_us.ErrKeyEmpty=Paste the key into the "Key" box (Ctrl+V), or go back and choose Standard Vega.
en_us.ErrKeyChars=The key can't contain spaces or quotation marks. Copy it again with the "Copy key" button.
en_us.ErrKeyPrefix=A key usually starts with AQ. or AIza. Use this one anyway?
en_us.ChromeStatus=Downloading and installing Google Chrome. This may take a few minutes...
en_us.ChromeFailed=Google Chrome could not be installed (no internet connection, or Google did not provide the installer). Vega works without it. You can install Chrome later and run the Vega installer again.
#endif

#ifdef LangEnGb
; ---------- English (United Kingdom) ----------
en_gb.UninstallName=Vega voice assistant
en_gb.TaskAutostart=Start Vega when I sign in to Windows (recommended)
en_gb.TaskDesktop=Desktop shortcut
en_gb.IconManual=Vega User Guide
en_gb.IconTelegram=Connect Telegram
en_gb.IconUninstall=Uninstall Vega
en_gb.StatusVoice=Installing the RHVoice voice…
en_gb.StatusChromeLink=Connecting Vega to Chrome…
en_gb.RunVega=Start Vega
en_gb.StatusTelegram=Opening the Telegram sign-in window…
en_gb.StatusLanguage=Downloading the voice and speech recognition… This may take a few minutes.
en_gb.KbNoFile=the update file is missing from the installer
en_gb.KbStatus=Installing Windows update KB3063858, which Vega needs. This will take a couple of minutes...
en_gb.KbDenied=Windows did not give permission (%1)
en_gb.KbCode=code %1
en_gb.KbFailed=Windows update KB3063858 couldn't be installed (%1). Without it, Vega won't start on this Windows 7 computer.%n%nRun the Vega installer again and allow the changes when Windows asks.
en_gb.EditionTitle=Choose your version of Vega
en_gb.EditionSub=Standard, or with Gemini AI?
en_gb.EditionText=Standard works without the internet. With Gemini, Vega is better at understanding unclear speech and commands in your own words: anything she didn't understand is sent to Google Gemini. This needs an internet connection and a free Google key.
en_gb.EditionStd=Standard (no internet needed)
en_gb.EditionGemini=With Gemini (understands more, needs a key)
en_gb.WarnTitle=Important: artificial intelligence
en_gb.WarnSub=Please read this to the end
en_gb.WarnText=In the Gemini version, some answers come from Google Gemini, an artificial intelligence. It is a computer programme, not a person. It can make mistakes, muddle facts and say things that are wrong while sounding completely sure of itself.%n%nDon't rely on its advice alone for decisions about your health, medicines, money, documents or safety. Speak to your GP, your family or a professional.%n%nWhat you say in a conversation with Gemini is sent to Google. Never say passwords, card numbers or codes from text messages.%n%nThe developer of Vega is not responsible for the AI's answers or for any decisions made on the basis of them.
en_gb.WarnAgree=I have read and understand this
en_gb.KeyTitle=Gemini key
en_gb.KeySub=How to get a free key. For step-by-step help, click "Read the guide" below
en_gb.KeyText=1. Click "Open Google website" below and sign in to your Google account (your Gmail address and password).%n2. If the site asks you to accept the terms, tick the box and click "Continue".%n3. In the top right-hand corner, click "Create API key".%n4. In the "Create a new key" window, leave the name as it is. Under "Choose an imported project", pick any project. If the list is empty, choose "Create project", type Vega and click "Create": the project will appear in that box.%n5. Click "Create key". The "API key details" window opens with your key (a long line of letters and numbers). Click "Copy key" at the bottom.%n6. Come back here, click in the "Key" box and press Ctrl+V. Then click "Next".
en_gb.KeyField=Key:
en_gb.KeySite=Open Google website
en_gb.KeyGuide=Read the guide
en_gb.NameTitle=Your name
en_gb.NameSub=What would you like Vega to call you?
en_gb.NameText=Optional. If you type your name, Vega will greet you by name, "Hello, John!", and sometimes use it when she talks to you. You can leave this empty and say later: "Vega, my name is John".
en_gb.NameField=Name:
en_gb.TgTitle=Telegram
en_gb.TgSub=Connect Telegram to Vega?
en_gb.TgText=Vega will read your new Telegram messages aloud and send messages for you by voice. Type the mobile number your Telegram account uses. After installation, a small window opens: Telegram will send you a code in a message, type it in there. You can also do this later with the "Vega" shortcut on the desktop.
en_gb.TgField=Mobile number, with country code:
en_gb.TgBox=Connect Telegram
en_gb.TgPrefix=+44
en_gb.ErrPhone=Please type the full mobile number with the country code, for example +447700900123. Or untick "Connect Telegram" to do it later.
en_gb.ErrWarn=Tick the box "I have read and understand this", or go back and choose Standard Vega.
en_gb.ErrKeyEmpty=Paste the key into the "Key" box (Ctrl+V), or go back and choose Standard Vega.
en_gb.ErrKeyChars=The key mustn't contain spaces or quotation marks. Copy it again with the "Copy key" button.
en_gb.ErrKeyPrefix=A key normally starts with AQ. or AIza. Use this one anyway?
en_gb.ChromeStatus=Downloading and installing Google Chrome. This may take a few minutes...
en_gb.ChromeFailed=Google Chrome couldn't be installed (no internet connection, or Google didn't provide the installer). Vega works without it. You can install Chrome later and run the Vega installer again.
#endif

#ifdef LangDe
; ---------- German ----------
de.UninstallName=Vega Sprachassistentin
de.TaskAutostart=Vega bei der Windows-Anmeldung starten (empfohlen)
de.TaskDesktop=Verknüpfung auf dem Desktop
de.IconManual=Vega Bedienungsanleitung
de.IconTelegram=Telegram verbinden
de.IconUninstall=Vega deinstallieren
de.StatusVoice=Die Stimme RHVoice wird installiert…
de.StatusChromeLink=Vega wird mit Chrome verbunden…
de.RunVega=Vega starten
de.StatusTelegram=Das Fenster zur Telegram-Anmeldung wird geöffnet…
de.StatusLanguage=Stimme und Spracherkennung werden heruntergeladen… Das kann einige Minuten dauern.
de.KbNoFile=die Update-Datei fehlt im Installationsprogramm
de.KbStatus=Das Windows-Update KB3063858, das Vega braucht, wird installiert. Das dauert ein paar Minuten...
de.KbDenied=Windows hat die Erlaubnis nicht erteilt (%1)
de.KbCode=Code %1
de.KbFailed=Das Windows-Update KB3063858 konnte nicht installiert werden (%1). Ohne dieses Update startet Vega unter diesem Windows 7 nicht.%n%nStarten Sie die Installation von Vega noch einmal und erlauben Sie die Änderungen, wenn Windows fragt.
de.EditionTitle=Version von Vega
de.EditionSub=Standard oder mit der KI Gemini?
de.EditionText=Die Standardversion funktioniert ohne Internet. Mit Gemini versteht Vega undeutliche Aussprache und frei formulierte Befehle besser: Was sie selbst nicht verstanden hat, wird an Google Gemini gesendet. Dafür brauchen Sie Internet und einen kostenlosen Google-Schlüssel.
de.EditionStd=Standard (ohne Internet)
de.EditionGemini=Mit Gemini (versteht mehr, Schlüssel nötig)
de.WarnTitle=Wichtig: künstliche Intelligenz
de.WarnSub=Bitte lesen Sie diesen Text bis zum Ende
de.WarnText=In der Version mit Gemini stammt ein Teil der Antworten von der künstlichen Intelligenz Google Gemini. Das ist ein Computerprogramm, kein Mensch. Es kann sich irren, Tatsachen verwechseln und Falsches mit großer Überzeugung sagen.%n%nTreffen Sie Entscheidungen über Gesundheit, Medikamente, Geld, Dokumente und Sicherheit nie allein auf ihren Rat hin. Sprechen Sie mit Ihrem Arzt, Ihrer Familie oder einer Fachperson.%n%nWas Sie im Gespräch mit Gemini sagen, wird an Google gesendet. Nennen Sie keine Passwörter, Kartennummern oder Codes aus SMS.%n%nDer Entwickler von Vega haftet nicht für die Antworten der künstlichen Intelligenz und nicht für die Folgen von Entscheidungen, die darauf beruhen.
de.WarnAgree=Ich habe das gelesen und verstanden
de.KeyTitle=Gemini-Schlüssel
de.KeySub=So bekommen Sie einen kostenlosen Schlüssel. Ausführlich: Schaltfläche „Anleitung lesen“ unten
de.KeyText=1. Klicken Sie unten auf „Google-Website öffnen“ und melden Sie sich bei Google an (Gmail-Adresse und Passwort).%n2. Wenn die Website Sie bittet, den Bedingungen zuzustimmen, setzen Sie das Häkchen und klicken Sie auf „Continue“.%n3. Klicken Sie oben rechts auf „Create API key“.%n4. Lassen Sie im Fenster „Create a new key“ den Namen unverändert. Wählen Sie im Feld „Choose an imported project“ ein beliebiges Projekt. Ist die Liste leer, wählen Sie „Create project“, geben Sie Vega ein und klicken Sie auf „Create“: Das Projekt erscheint dann in diesem Feld.%n5. Klicken Sie auf „Create key“. Das Fenster „API key details“ öffnet sich mit Ihrem Schlüssel (eine lange Zeichenfolge). Klicken Sie unten auf „Copy key“.%n6. Kehren Sie hierher zurück, klicken Sie in das Feld „Schlüssel“ und drücken Sie Strg+V. Klicken Sie dann auf „Weiter“.
de.KeyField=Schlüssel:
de.KeySite=Google-Website öffnen
de.KeyGuide=Anleitung lesen
de.NameTitle=Ihr Name
de.NameSub=Wie soll Vega Sie ansprechen?
de.NameText=Freiwillig. Wenn Sie Ihren Namen eingeben, begrüßt Vega Sie mit Namen: „Hallo, Thomas!“ und spricht Sie im Gespräch manchmal mit Namen an. Sie können das Feld leer lassen und später sagen: „Vega, ich heiße Thomas“.
de.NameField=Name:
de.TgTitle=Telegram
de.TgSub=Telegram mit Vega verbinden?
de.TgText=Vega liest neue Telegram-Nachrichten laut vor und verschickt Nachrichten per Sprache. Geben Sie die Telefonnummer ein, mit der Ihr Telegram verknüpft ist. Nach der Installation öffnet sich ein kleines Fenster: Telegram schickt Ihnen einen Code per Nachricht, den Sie dort eingeben. Sie können das auch später machen, über die Verknüpfung „Vega“ auf dem Desktop.
de.TgField=Telefonnummer mit Ländervorwahl:
de.TgBox=Telegram verbinden
de.TgPrefix=+49
de.ErrPhone=Bitte geben Sie die vollständige Telefonnummer mit Ländervorwahl ein, zum Beispiel +4915112345678. Oder entfernen Sie das Häkchen bei „Telegram verbinden“, um es später zu tun.
de.ErrWarn=Setzen Sie das Häkchen bei „Ich habe das gelesen und verstanden“ oder gehen Sie zurück und wählen Sie die Standardversion.
de.ErrKeyEmpty=Fügen Sie den Schlüssel in das Feld „Schlüssel“ ein (Strg+V) oder gehen Sie zurück und wählen Sie die Standardversion.
de.ErrKeyChars=Der Schlüssel darf keine Leerzeichen oder Anführungszeichen enthalten. Kopieren Sie ihn noch einmal mit „Copy key“.
de.ErrKeyPrefix=Ein Schlüssel beginnt normalerweise mit AQ. oder AIza. Diesen trotzdem verwenden?
de.ChromeStatus=Google Chrome wird heruntergeladen und installiert. Das kann einige Minuten dauern...
de.ChromeFailed=Google Chrome konnte nicht installiert werden (kein Internet, oder Google hat das Installationsprogramm nicht geliefert). Vega funktioniert auch ohne Chrome. Sie können Chrome später installieren und das Installationsprogramm von Vega noch einmal starten.
#endif

#ifdef LangIt
; ---------- Italian ----------
it.UninstallName=Vega, assistente vocale
it.TaskAutostart=Avvia Vega all'accesso a Windows (consigliato)
it.TaskDesktop=Icona sul desktop
it.IconManual=Guida di Vega
it.IconTelegram=Collega Telegram
it.IconUninstall=Disinstalla Vega
it.StatusVoice=Installazione della voce RHVoice…
it.StatusChromeLink=Collegamento di Vega a Chrome…
it.RunVega=Avvia Vega
it.StatusTelegram=Apertura della finestra di accesso a Telegram…
it.StatusLanguage=Download della voce e del riconoscimento vocale in corso… Può richiedere qualche minuto.
it.KbNoFile=nel programma di installazione manca il file dell'aggiornamento
it.KbStatus=Installazione dell'aggiornamento di Windows KB3063858, necessario a Vega. Ci vorrà qualche minuto...
it.KbDenied=Windows non ha concesso l'autorizzazione (%1)
it.KbCode=codice %1
it.KbFailed=Non è stato possibile installare l'aggiornamento di Windows KB3063858 (%1). Senza di esso Vega non si avvia su questo Windows 7.%n%nAvvia di nuovo l'installazione di Vega e consenti le modifiche quando Windows lo chiede.
it.EditionTitle=Versione di Vega
it.EditionSub=Normale o con l'intelligenza artificiale Gemini?
it.EditionText=La versione normale funziona senza internet. Con Gemini, Vega capisce meglio una pronuncia poco chiara e i comandi detti con parole proprie: le frasi che non ha capito da sola vengono inviate a Google Gemini. Servono internet e una chiave Google gratuita.
it.EditionStd=Normale (senza internet)
it.EditionGemini=Con Gemini (capisce di più, serve una chiave)
it.WarnTitle=Importante: intelligenza artificiale
it.WarnSub=Per favore, leggi fino in fondo
it.WarnText=Nella versione con Gemini una parte delle risposte arriva dall'intelligenza artificiale Google Gemini. È un programma, non una persona. Può sbagliare, confondere i fatti e dire cose false con tono sicuro.%n%nNon prendere decisioni su salute, farmaci, soldi, documenti e sicurezza basandoti solo sui suoi consigli. Chiedi al tuo medico, ai familiari o a un esperto.%n%nLe frasi della conversazione con Gemini vengono inviate a Google. Non dire mai password, numeri di carta o codici ricevuti per SMS.%n%nLo sviluppatore di Vega non è responsabile delle risposte dell'intelligenza artificiale né delle conseguenze delle decisioni prese in base a esse.
it.WarnAgree=Ho letto e ho capito
it.KeyTitle=Chiave Gemini
it.KeySub=Come ottenere una chiave gratuita. Spiegazione completa: pulsante «Leggi la guida» qui sotto
it.KeyText=1. Premi il pulsante «Apri il sito di Google» qui sotto e accedi al tuo account Google (indirizzo Gmail e password).%n2. Se il sito chiede di accettare i termini, metti la spunta e premi «Continue».%n3. In alto a destra premi «Create API key».%n4. Nella finestra «Create a new key» non cambiare il nome. Nel campo «Choose an imported project» scegli un progetto qualsiasi. Se l'elenco è vuoto, scegli «Create project», scrivi Vega e premi «Create»: il progetto comparirà in quel campo.%n5. Premi «Create key». Si apre la finestra «API key details» con la tua chiave (una lunga riga di lettere e numeri). Premi «Copy key» in basso.%n6. Torna qui, fai clic nel campo «Chiave» e premi Ctrl+V. Poi premi «Avanti».
it.KeyField=Chiave:
it.KeySite=Apri il sito di Google
it.KeyGuide=Leggi la guida
it.NameTitle=Il tuo nome
it.NameSub=Come deve chiamarti Vega?
it.NameText=Facoltativo. Se scrivi il tuo nome, Vega ti saluterà per nome: «Ciao, Marco!» e a volte ti chiamerà per nome mentre parlate. Puoi lasciarlo vuoto e dire più tardi: «Vega, mi chiamo Marco».
it.NameField=Nome:
it.TgTitle=Telegram
it.TgSub=Collegare Telegram a Vega?
it.TgText=Vega leggerà ad alta voce i nuovi messaggi di Telegram e invierà messaggi con la voce. Scrivi il numero di telefono collegato al tuo Telegram. Dopo l'installazione si aprirà una piccola finestra: Telegram ti manderà un codice in un messaggio, scrivilo lì. Puoi farlo anche in seguito, con l'icona «Vega» sul desktop.
it.TgField=Numero di telefono con prefisso internazionale:
it.TgBox=Collega Telegram
it.TgPrefix=+39
it.ErrPhone=Scrivi il numero di telefono completo con il prefisso internazionale, per esempio +393471234567. Oppure togli la spunta da «Collega Telegram» per farlo in seguito.
it.ErrWarn=Metti la spunta su «Ho letto e ho capito» oppure torna indietro e scegli la versione normale.
it.ErrKeyEmpty=Incolla la chiave nel campo «Chiave» (Ctrl+V) oppure torna indietro e scegli la versione normale.
it.ErrKeyChars=La chiave non deve contenere spazi né virgolette. Copiala di nuovo con il pulsante «Copy key».
it.ErrKeyPrefix=Di solito la chiave inizia con AQ. o AIza. Vuoi usare comunque questa?
it.ChromeStatus=Download e installazione di Google Chrome in corso. Può richiedere qualche minuto...
it.ChromeFailed=Non è stato possibile installare Google Chrome (manca la connessione a internet oppure Google non ha fornito il programma di installazione). Vega funziona anche senza. Puoi installare Chrome più tardi e avviare di nuovo l'installazione di Vega.
#endif

