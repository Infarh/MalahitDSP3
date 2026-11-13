# AGENTS.md

Инструкции для кодовых агентов, работающих в этом репозитории. Формат
`AGENTS.md` читают GitHub Copilot, OpenAI Codex и другие агенты; для VS Code
Copilot дополнительно действует указатель в
[.github/copilot-instructions.md](./.github/copilot-instructions.md).

## Что это за проект

Инструментарий для SDR-приёмника **Malahit DSP3**, подключённого по USB:
управление по CAT и захват сырого I/Q. Единственное «приложение» — CLI
[malahit.py](./malahit.py). Вендорского SDK нет, весь протокол выяснен
экспериментально.

## Окружение

- Железо подключено к этой машине: композитное USB-устройство
  `VID_FFFF&PID_0737` с четырьмя интерфейсами (CAT-порт + три аудио).
- **Не хардкодьте номер COM-порта.** Определяйте по VID/PID:

  ```python
  port = next((p.device for p in list_ports.comports()
               if p.vid == 0xFFFF and p.pid == 0x0737), None)
  ```

- Аудиоустройства ищите по имени (`Malahit IQ`, `Malahit RX`,
  `Malahit Headphone`) — индексы меняются после переподключения.
- Python 3.12. Зависимости — только `numpy`, `sounddevice`, `pyserial`
  ([requirements.txt](./requirements.txt)). Не добавляйте тяжёлые DSP-фреймворки
  ради одной задачи.

## Структура

```
malahit.py                              весь CLI: discovery, CAT, захват, DSP
tests/test_malahit.py                   unittest, работает без железа
.github/skills/malahit-dsp3-control/    CAT: команды, ловушки
.github/skills/malahit-iq-capture/      I/Q, WDM-KS, демодуляция
.github/skills/malahit-firmware-update/ DFU, dfu-util, Zadig
.vscode/tasks.json                      задачи: info, get, scan, record, tests
```

Новую функциональность добавляйте подкомандой в `malahit.py`, а не отдельным
скриптом. Чистые функции (разбор частоты, WAV, демодуляция) держите
отделёнными от ввода-вывода — их покрывают тесты.

## Язык

- `README.md`, `AGENTS.md` и всё, что читает пользователь, — **по-русски**.
- Код, имена, комментарии в коде, `SKILL.md` — **по-английски**.

## Проверка изменений

```powershell
python -m unittest discover -s tests -v
python malahit.py info
python malahit.py get
```

Тесты не должны требовать подключённого приёмника. Всё, что требует железа,
проверяйте вручную подкомандами `info` / `get` / `scan`.

## Обязательные ограничения (проверено на железе)

- **WDM-KS не поддерживает блокирующий API PortAudio.** `sd.rec()` и
  `stream.read()` падают с `PortAudioError -9999` /
  `'Blocking API not supported yet'`. Захват — только через callback
  (`IqStream` в `malahit.py`).
- **`SM` требует параметр:** `SM0;`. Голый `SM;` возвращает `?;`.
- **Версию прошивки по CAT получить нельзя.** `FV;` — жёстко прописанная
  строка `FV1.00;`, а не версия. Версия видна только в меню RADIO.
- Частоты в CAT — 11 цифр в герцах с ведущими нулями (`FA00010050000;`).
- В I/Q канале **L = I, R = Q**; корреляция I и Q должна быть близка к нулю.
  Высокая корреляция означает, что открыто не то устройство.
- **Не прошивайте приёмник без явного подтверждения пользователя.** Запись
  требует `:force` (первые 48 КиБ помечены read-only), а ошибка `get_status`
  после `File downloaded successfully` — норма, не сбой.

## Стиль

- Только stdlib + перечисленные зависимости.
- Не подавляйте ошибки молча: подкоманды печатают `error: ...` в stderr и
  возвращают код 1.
- Временные файлы (WAV, архивы прошивок) не оставляйте в рабочей папке —
  используйте `%TEMP%` и удаляйте после проверки.
- Записи I/Q и другие артефакты захвата в репозиторий не коммитьте
  (см. [.gitignore](./.gitignore)).
