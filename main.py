import os
import queue
import sys
import time

try:
    import keyboard
except ImportError:
    print("Ошибка: библиотека 'keyboard' не установлена.")
    print("Установите: pip install keyboard")
    sys.exit(1)

# Настройки таймера
MOVE_WINDOW = 0.5
FREEZE_TIME = 2.0
TOGGLE_KEY = 'f1'

WALK_KEYS = {'w', 'a', 's', 'd', 'up', 'down', 'left', 'right'}
POLL_INTERVAL = 0.001
DISPLAY_INTERVAL = 0.05

# Callback клавиатуры работают в отдельных потоках. Они только добавляют
# события в эту очередь; все состояние и таймеры принадлежат главному циклу.
events = queue.Queue()
blocked_hooks = {}


def on_key_event(event):
    """Передает события WASD/стрелок главному циклу без ожидания."""
    if event.event_type in {'down', 'up'} and isinstance(event.name, str):
        key_name = event.name.lower()
        if key_name in WALK_KEYS:
            events.put(('key', (key_name, event.event_type, time.monotonic())))


def request_toggle():
    """Передает запрос F1 главному циклу, не меняя состояние здесь."""
    events.put(('toggle', None))

def lock_walk_keys():
    """Блокирует клавиши ходьбы и посылает для них отпускание."""
    failures = []

    # Сначала устанавливаем блокировку, затем отпускаем возможные удержания.
    for key in WALK_KEYS:
        if key in blocked_hooks:
            continue
        try:
            blocked_hooks[key] = keyboard.block_key(key)
        except Exception as exc:
            failures.append(f"block {key}: {exc}")

    for key in WALK_KEYS:
        try:
            keyboard.release(key)
        except Exception as exc:
            failures.append(f"release {key}: {exc}")

    return failures

def unlock_walk_keys():
    """Снимает все установленные блокировки клавиш ходьбы."""
    for unhook_fn in blocked_hooks.values():
        try:
            unhook_fn()
        except Exception:
            pass
    blocked_hooks.clear()


def display_status(enabled, message):
    """Обновляет статус в одной строке консоли."""
    status = "ВКЛ" if enabled else "ВЫКЛ"
    output = f"\rСтатус: [{status}] | F1: переключить | {message}"
    print(output.ljust(110), end="", flush=True)

def main():
    os.system('cls' if os.name == 'nt' else 'clear')

    print("=" * 65)
    print("               ROBLOX TIMEBOMB HELPER                 ")
    print("=" * 65)
    print(f"{TOGGLE_KEY.upper()} - включить или выключить отслеживание")
    print(f"Окно движения: {MOVE_WINDOW:.1f} сек | Блокировка: {FREEZE_TIME:.1f} сек")
    print("Триггеры: WASD и стрелки. Пробел не блокируется и не запускает таймер.")
    print("=" * 65)
    print("Для глобального перехвата клавиш в Windows могут потребоваться права администратора.")
    print("=" * 65)
    print()

    enabled = False
    cycle_start = None
    frozen = False
    freeze_deadline = None
    accept_after = 0.0
    pressed_walk_keys = set()
    next_display = 0.0
    hook_handle = None
    hotkey_handle = None

    display_status(enabled, "Нажмите F1 для начала.")

    try:
        # Callback-ы только ставят сообщения в очередь. В частности, здесь
        # нет ожиданий, блокировок клавиш и изменения состояния таймера.
        hook_handle = keyboard.hook(on_key_event, suppress=False)
        hotkey_handle = keyboard.add_hotkey(
            TOGGLE_KEY, request_toggle, suppress=False
        )

        while True:
            now = time.monotonic()
            while True:
                try:
                    event_type, timestamp = events.get_nowait()
                except queue.Empty:
                    break

                if event_type == 'toggle':
                    enabled = not enabled
                    if not enabled:
                        unlock_walk_keys()
                        cycle_start = None
                        frozen = False
                        freeze_deadline = None
                        accept_after = time.monotonic()
                        display_status(enabled, "Отслеживание выключено.")
                    else:
                        cycle_start = None
                        frozen = False
                        freeze_deadline = None
                        accept_after = time.monotonic()
                        display_status(enabled, "Ожидание WASD или стрелки...")
                elif event_type == 'key':
                    key_name, key_action, timestamp = timestamp
                    if key_action == 'up':
                        pressed_walk_keys.discard(key_name)
                    elif key_name not in pressed_walk_keys:
                        pressed_walk_keys.add(key_name)
                        if (
                            enabled
                            and cycle_start is None
                            and timestamp >= accept_after
                        ):
                            # Используем время события, чтобы задержка очереди
                            # не увеличивала окно движения.
                            cycle_start = timestamp
                            frozen = False
                            freeze_deadline = None

            if enabled and cycle_start is not None:
                elapsed = time.monotonic() - cycle_start

                if elapsed >= MOVE_WINDOW and not frozen:
                    failures = lock_walk_keys()
                    frozen = True
                    freeze_deadline = time.monotonic() + FREEZE_TIME
                    # Блокирующий hook может скрыть событие key-up, поэтому
                    # не переносим состояние удержания через фазу блокировки.
                    pressed_walk_keys.clear()
                    if failures:
                        print("\nПредупреждение: не все клавиши удалось блокировать:")
                        for failure in failures:
                            print(f"  {failure}")

                if frozen and time.monotonic() >= freeze_deadline:
                    unlock_walk_keys()
                    accept_after = freeze_deadline
                    cycle_start = None
                    frozen = False
                    freeze_deadline = None
                    pressed_walk_keys.clear()

            if now >= next_display:
                if not enabled:
                    message = "Нажмите F1 для начала."
                elif cycle_start is None:
                    message = "Ожидание WASD или стрелки..."
                elif frozen:
                    remaining = max(0.0, freeze_deadline - time.monotonic())
                    message = f"ЗАМОРОЗКА | осталось {remaining:.2f} сек"
                else:
                    remaining = max(0.0, MOVE_WINDOW - elapsed)
                    message = f"ДВИЖЕНИЕ | осталось {remaining:.2f} сек"

                display_status(enabled, message)
                next_display = now + DISPLAY_INTERVAL

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\nОстановка скрипта.")
    finally:
        unlock_walk_keys()
        if hotkey_handle is not None:
            keyboard.remove_hotkey(hotkey_handle)
        if hook_handle is not None:
            keyboard.unhook(hook_handle)
        print("\nСкрипт остановлен.")

if __name__ == "__main__":
    main()