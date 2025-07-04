import pygame
import asyncio
from js import Image, document, window, WebSocket, JSON
from pyodide.ffi import create_proxy
import json
from js import document as js_document

# Debug flag to control console output
DEBUG = False

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

pygame.init()
pygame.font.init()
# Use a pixel-art font (ensure it's available in /static/assets/fonts)
try:
    font = pygame.font.Font("/static/assets/fonts/pixel_font.ttf", 16)
except:
    font = pygame.font.SysFont("arial", 16)
    debug_print("Warning: Pixel font not found, using Arial")

canvas = document.getElementById("canvas")
debug_print("Canvas found:", canvas)
# Set smaller viewport for zoom without stretching
viewport_width = 800
viewport_height = 600
canvas.width = viewport_width
canvas.height = viewport_height
canvas.style.imageRendering = "pixelated"
debug_print(f"Canvas attributes set: {canvas.width}x{canvas.height} (viewport: {viewport_width}x{viewport_height})")
screen = pygame.display.set_mode((viewport_width, viewport_height))
debug_print("Pygame display initialized")

world_width = 1000
world_height = 1000
world = pygame.Surface((world_width, world_height))

player_rect = pygame.Rect(100, 100, 40, 40)
player_speed = 3
dodge_speed = 6
dodge_duration = 0.3
dodge_cooldown = 0.5
attack_duration = 0.5
attack_cooldown = 0.3

nickname = window.prompt("Enter your nickname:") or "player"
debug_print(f"Nickname: {nickname}")

clock = pygame.time.Clock()
running = True
big_bg = None

def redraw_world_background():
    global big_bg
    if not big_bg:
        debug_print("Warning: big_bg is None, filling with gray")
        world.fill((128, 128, 128))
        return
    tile = pygame.transform.smoothscale(big_bg, (128, 128))
    for x in range(0, world_width, tile.get_width()):
        for y in range(0, world_height, tile.get_height()):
            world.blit(tile, (x, y))
    debug_print("World background redrawn")

def on_resize(evt):
    global screen, viewport_width, viewport_height
    canvas = document.getElementById("canvas")
    canvas.width = viewport_width
    canvas.height = viewport_height
    canvas.style.imageRendering = "pixelated"
    screen = pygame.display.set_mode((viewport_width, viewport_height))
    debug_print("Resized canvas to:", viewport_width, viewport_height)
    redraw_world_background()

window.addEventListener("resize", create_proxy(on_resize))

async def load_image(url):
    try:
        debug_print(f"Loading image: {url}")
        img = Image.new()
        img.src = url
        while not img.complete:
            await asyncio.sleep(0.05)
        if img.width == 0 or img.height == 0:
            raise ValueError(f"Failed to load image: {url}")
        canvas = document.createElement("canvas")
        canvas.width = img.width
        canvas.height = img.height
        ctx = canvas.getContext("2d")
        ctx.drawImage(img, 0, 0)
        img_data = ctx.getImageData(0, 0, img.width, img.height)
        pixels = bytes(img_data.data.to_py())
        surface = pygame.image.frombuffer(pixels, (img.width, img.height), "RGBA")
        debug_print(f"Successfully loaded image: {url}")
        return surface
    except Exception as e:
        debug_print(f"Error loading image {url}: {e}")
        return None

def slice_sprite_strip(sheet, num_frames):
    if not sheet:
        debug_print("Warning: sprite sheet is None")
        return [], 0, 0
    frame_width = sheet.get_width() // num_frames
    frame_height = sheet.get_height()
    frames = []
    for i in range(num_frames):
        frame = pygame.Surface((frame_width, frame_height), pygame.SRCALPHA)
        frame.blit(sheet, (0, 0), pygame.Rect(i * frame_width, 0, frame_width, frame_height))
        frames.append(frame)
    return frames, frame_width, frame_height

async def load_player_animations(base_path):
    states = ['attack1', 'attack2', 'idle', 'run']
    directions = ['down', 'left', 'right', 'up']
    frame_counts = {'attack1': 8, 'attack2': 8, 'idle': 8, 'run': 8}
    animations = {}
    frame_width, frame_height = None, None
    for state in states:
        animations[state] = {}
        for direction in directions:
            filename = f"{state}_{direction}.png"
            path = f"{base_path}/{state}/{filename}"
            debug_print(f"Loading sprite: {path}")
            sheet = await load_image(path)
            if sheet:
                frames, fw, fh = slice_sprite_strip(sheet, frame_counts[state])
                animations[state][direction] = frames
                if frame_width is None:
                    frame_width, frame_height = fw, fh
                debug_print(f"Successfully loaded sprite: {path}")
            else:
                debug_print(f"Failed to load sprite {path}")
                animations[state][direction] = []
    return animations, frame_width or 40, frame_height or 40

class PlayerAnimation:
    def __init__(self, animations, frame_duration=0.1):
        self.animations = animations
        self.state = 'idle'
        self.direction = 'down'
        self.frame_duration = frame_duration
        self.current_time = 0
        self.current_frame = 0
        self.attack_timer = 0
        self.dodge_timer = 0
        self.dodge_cooldown_timer = 0
        self.cooldown_timer = 0
        self.afterimages = []
        self.last_space_press = 0
        self.queued_attack = None

    def update(self, dt):
        self.afterimages = [(x, y, frame, alpha, time - dt) for x, y, frame, alpha, time in self.afterimages if time > 0]
        if self.dodge_cooldown_timer > 0:
            self.dodge_cooldown_timer -= dt
        if self.cooldown_timer > 0:
            self.cooldown_timer -= dt
        if self.state == 'dodge':
            self.dodge_timer -= dt
            if self.dodge_timer <= 0:
                self.state = 'idle'
                self.queued_attack = None
        elif self.state in ['attack1', 'attack2']:
            self.attack_timer -= dt
            if self.attack_timer <= 0:
                if self.state == 'attack1' and self.queued_attack == 'attack2':
                    self.state = 'attack2'
                    self.attack_timer = attack_duration
                    self.queued_attack = None
                    debug_print("Starting queued attack2")
                else:
                    self.state = 'idle'
                    self.cooldown_timer = attack_cooldown if self.state == 'attack2' else 0
                    self.queued_attack = None
                    debug_print("Attack finished, cooldown applied" if self.cooldown_timer > 0 else "Attack finished")
        frames = self.animations.get(self.state if self.state != 'dodge' else 'run', {}).get(self.direction, [])
        if not frames:
            return
        self.current_time += dt
        while self.current_time >= self.frame_duration:
            self.current_time -= self.frame_duration
            self.current_frame = (self.current_frame + 1) % len(frames)

    def trigger_attack(self, current_time):
        if self.state in ['attack1', 'attack2', 'dodge'] or self.attack_timer > 0 or self.cooldown_timer > 0:
            if self.state == 'attack1' and current_time - self.last_space_press < 0.3 and self.queued_attack is None:
                self.queued_attack = 'attack2'
                debug_print("Queued attack2")
            return
        self.last_space_press = current_time
        self.state = 'attack1'
        self.attack_timer = attack_duration
        self.queued_attack = None
        debug_print("Triggered attack1")

    def trigger_dodge(self, direction, x, y):
        if self.dodge_cooldown_timer > 0 or self.state in ['attack1', 'attack2']:
            return False
        self.dodge_timer = dodge_duration
        self.dodge_cooldown_timer = dodge_cooldown
        self.state = 'dodge'
        self.queued_attack = None
        self.direction = direction
        self.afterimages.append((x, y, self.get_frame(), 200, 0.2))
        self.afterimages.append((x, y, self.get_frame(), 150, 0.1))
        debug_print("Triggered dodge")
        return True

    def get_frame(self):
        frames = self.animations.get(self.state if self.state != 'dodge' else 'run', {}).get(self.direction, [])
        if frames and self.state == 'dodge':
            frame = frames[self.current_frame].copy()
            frame.fill((255, 255, 255, 128), special_flags=pygame.BLEND_RGBA_MULT)
            return frame
        return frames[self.current_frame] if frames else None

class Player:
    def __init__(self, x, y, animations, width, height):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.animator = PlayerAnimation(animations)

class MultiplayerClient:
    def __init__(self, player, nickname, animations):
        self.player = player
        self.nickname = nickname
        self.animations = animations
        self.ws = None
        self.other_players = {}
        self.connected = False
        self.is_invulnerable = False
        self.on_open_proxy = create_proxy(self._on_open)
        self.on_message_proxy = create_proxy(self._on_message)
        self.on_error_proxy = create_proxy(self._on_error)
        self.on_close_proxy = create_proxy(self._on_close)

    async def connect(self):
        try:
            self.ws = WebSocket.new(f"ws://{window.location.host}/ws")
            self.ws.addEventListener("open", self.on_open_proxy)
            self.ws.addEventListener("message", self.on_message_proxy)
            self.ws.addEventListener("error", self.on_error_proxy)
            self.ws.addEventListener("close", self.on_close_proxy)
            self._open_promise = asyncio.Future()
            await self._open_promise
            self.connected = True
            self.send({
                "type": "join",
                "nickname": self.nickname,
                "x": self.player.x,
                "y": self.player.y,
                "state": self.player.animator.state,
                "direction": self.player.animator.direction,
                "current_frame": self.player.animator.current_frame,
                "current_time": self.player.animator.current_time,
                "is_invulnerable": self.is_invulnerable,
                "afterimages": self.player.animator.afterimages
            })
            debug_print("WebSocket connection established")
        except Exception as e:
            debug_print(f"WebSocket connection failed: {e}")

    def _on_open(self, event):
        debug_print("WebSocket connected")
        if not self._open_promise.done():
            self._open_promise.set_result(True)

    def _on_message(self, event):
        try:
            data = json.loads(event.data)
            debug_print(f"Received message: {data}")
            if data.get("type") == "players_update":
                self.other_players = {
                    p["nickname"]: {
                        "x": p["x"],
                        "y": p["y"],
                        "state": p.get("state", "idle"),
                        "direction": p.get("direction", "down"),
                        "current_frame": p.get("current_frame", 0),
                        "current_time": p.get("current_time", 0),
                        "is_invulnerable": p.get("is_invulnerable", False),
                        "afterimages": p.get("afterimages", [])
                    }
                    for p in data["players"]
                    if p["nickname"] != self.nickname
                }
        except Exception as e:
            debug_print(f"Error processing message: {e}")

    def _on_close(self, event):
        debug_print("WebSocket closed")
        self.connected = False
        if not self._open_promise.done():
            self._open_promise.set_exception(RuntimeError("WebSocket closed"))
        self._cleanup()

    def _on_error(self, event):
        debug_print(f"WebSocket error: {event}")
        self.connected = False
        if not self._open_promise.done():
            self._open_promise.set_exception(RuntimeError("WebSocket error"))
        self._cleanup()

    def send(self, data):
        if self.ws and self.ws.readyState == 1:
            try:
                message = json.dumps(data)
                if message == "{}":
                    debug_print(f"Warning: json.dumps produced empty object for data: {data}")
                    return
                if data.get("type") != "update":
                    debug_print(f"Sending message: {message}")
                self.ws.send(message)
            except Exception as e:
                debug_print(f"Error sending message: {e}")
        else:
            debug_print("WebSocket not open. Could not send:", data)

    def send_position_update(self):
        self.send({
            "type": "update",
            "x": self.player.x,
            "y": self.player.y,
            "state": self.player.animator.state,
            "direction": self.player.animator.direction,
            "current_frame": self.player.animator.current_frame,
            "current_time": self.player.animator.current_time,
            "is_invulnerable": self.player.animator.state == 'dodge',
            "afterimages": [(x, y, alpha, time) for x, y, _, alpha, time in self.player.animator.afterimages]
        })

    def get_other_players(self):
        return self.other_players

    async def keep_alive(self):
        while self.connected:
            await asyncio.sleep(20)
            self.send({"type": "ping"})

    def _cleanup(self):
        if self.ws:
            self.ws.removeEventListener("open", self.on_open_proxy)
            self.ws.removeEventListener("message", self.on_message_proxy)
            self.ws.removeEventListener("error", self.on_error_proxy)
            self.ws.removeEventListener("close", self.on_close_proxy)
        self.on_open_proxy.destroy()
        self.on_message_proxy.destroy()
        self.on_error_proxy.destroy()
        self.on_close_proxy.destroy()

async def game_loop():
    global running, big_bg
    canvas.focus()
    debug_print(f"Canvas found: {canvas}")

    pressed_keys = set()
    space_pressed = False

    def on_keydown(event):
        nonlocal space_pressed
        debug_print(f"JavaScript key down: key={event.key}, code={event.code}, keyCode={event.keyCode}")
        if event.keyCode == 32 and not space_pressed:
            space_pressed = True
            pressed_keys.add(event.keyCode)
        elif event.keyCode != 32:
            pressed_keys.add(event.keyCode)

    def on_keyup(event):
        nonlocal space_pressed
        debug_print(f"JavaScript key up: key={event.key}, code={event.code}, keyCode={event.keyCode}")
        if event.keyCode == 32:
            space_pressed = False
        pressed_keys.discard(event.keyCode)

    js_document.addEventListener("keydown", create_proxy(on_keydown))
    js_document.addEventListener("keyup", create_proxy(on_keyup))

    def on_canvas_click(event):
        canvas.focus()
        debug_print("Canvas clicked, focused")
    canvas.addEventListener("click", create_proxy(on_canvas_click))

    try:
        debug_print("Loading player animations...")
        player_animations, player_w, player_h = await load_player_animations("/static/assets/sprites/player")
        debug_print("Player animations loaded successfully")
        player = Player(100, 100, player_animations, player_w, player_h)
    except Exception as e:
        debug_print(f"Failed to load player animations: {e}")
        player = Player(100, 100, {}, 40, 40)

    try:
        mp_client = MultiplayerClient(player, nickname, player_animations)
        debug_print("Connecting to WebSocket...")
        await mp_client.connect()
        debug_print("WebSocket connection established")
    except Exception as e:
        debug_print(f"Failed to connect to WebSocket: {e}")
        mp_client = None

    try:
        debug_print("Loading background image...")
        big_bg = await load_image("/static/assets/background/grass.png")
        if big_bg:
            debug_print("Background image loaded successfully")
            redraw_world_background()
        else:
            debug_print("Background image not loaded, using fallback")
    except Exception as e:
        debug_print(f"Failed to load background: {e}")

    player_anim = player.animator
    last_time = pygame.time.get_ticks() / 1000
    frame_count = 0

    asyncio.ensure_future(mp_client.keep_alive() if mp_client else asyncio.sleep(0))

    while running:
        try:
            debug_print(f"Game loop iteration: {frame_count}, running: {running}")
            current_time = pygame.time.get_ticks() / 1000
            dt = current_time - last_time
            last_time = current_time

            if mp_client:
                mp_client.send_position_update()

            canvas.focus()
            debug_print(f"Canvas focused: {canvas == js_document.activeElement}")

            for event in pygame.event.get():
                debug_print(f"Processing event: type={event.type}, key={getattr(event, 'key', 'N/A')}")
                if event.type == pygame.QUIT:
                    running = False

            moving = False
            direction = player_anim.direction
            speed = dodge_speed if player_anim.state == 'dodge' else player_speed
            keys = pygame.key.get_pressed()
            if (keys[pygame.K_LEFT] or 37 in pressed_keys) and player_anim.state not in ['attack1', 'attack2']:
                player.x -= speed
                direction = 'left'
                moving = True
                debug_print(f"Moving left: player.x={player.x}")
            elif (keys[pygame.K_RIGHT] or 39 in pressed_keys) and player_anim.state not in ['attack1', 'attack2']:
                player.x += speed
                direction = 'right'
                moving = True
                debug_print(f"Moving right: player.x={player.x}")
            elif (keys[pygame.K_UP] or 38 in pressed_keys) and player_anim.state not in ['attack1', 'attack2']:
                player.y -= speed
                direction = 'up'
                moving = True
                debug_print(f"Moving up: player.y={player.y}")
            elif (keys[pygame.K_DOWN] or 40 in pressed_keys) and player_anim.state not in ['attack1', 'attack2']:
                player.y += speed
                direction = 'down'
                moving = True
                debug_print(f"Moving down: player.y={player.y}")
            if space_pressed:
                player_anim.trigger_attack(current_time)
                if mp_client and player_anim.state in ['attack1', 'attack2']:
                    mp_client.send({
                        "type": "action",
                        "action": "attack",
                        "x": player.x,
                        "y": player.y,
                        "state": player_anim.state,
                        "direction": player_anim.direction,
                        "current_frame": player_anim.current_frame,
                        "current_time": player_anim.current_time,
                        "is_invulnerable": player_anim.state == 'dodge',
                        "afterimages": [(x, y, alpha, time) for x, y, _, alpha, time in player_anim.afterimages]
                    })
                    debug_print("Triggered attack")
            elif (keys[pygame.K_LSHIFT] or 16 in pressed_keys) and moving and player_anim.dodge_cooldown_timer <= 0:
                if player_anim.trigger_dodge(direction, player.x, player.y):
                    if direction == 'left':
                        player.x -= speed
                    elif direction == 'right':
                        player.x += speed
                    elif direction == 'up':
                        player.y -= speed
                    elif direction == 'down':
                        player.y += speed
                    if mp_client:
                        mp_client.send({
                            "type": "action",
                            "action": "dodge",
                            "x": player.x,
                            "y": player.y,
                            "state": player_anim.state,
                            "direction": player_anim.direction,
                            "current_frame": player_anim.current_frame,
                            "current_time": player_anim.current_time,
                            "is_invulnerable": player_anim.state == 'dodge',
                            "afterimages": [(x, y, alpha, time) for x, y, _, alpha, time in player_anim.afterimages]
                        })
                        debug_print("Triggered dodge")

            player.x = max(0, min(world_width - player.width, player.x))
            player.y = max(0, min(world_height - player.height, player.y))
            debug_print(f"Player position: ({player.x}, {player.y})")

            player_anim.state = 'run' if moving and player_anim.state not in ['attack1', 'attack2', 'dodge'] else player_anim.state
            if not moving and player_anim.state not in ['attack1', 'attack2', 'dodge']:
                player_anim.state = 'idle'
            player_anim.direction = direction
            player_anim.update(dt)

            camera_x = player.x + player.width // 2 - viewport_width // 2
            camera_y = player.y + player.height // 2 - viewport_height // 2
            camera_x = max(0, min(world_width - viewport_width, camera_x))
            camera_y = max(0, min(world_height - viewport_height, camera_y))

            screen.fill((128, 128, 128))
            if big_bg:
                debug_print(f"big_bg: {big_bg is not None}, world size: {world.get_size()}")
                screen.blit(world, (0, 0), area=pygame.Rect(camera_x, camera_y, viewport_width, viewport_height))
            else:
                debug_print("No background, using gray fill")

            for x, y, frame, alpha, _ in player_anim.afterimages:
                if frame:
                    afterimage = frame.copy()
                    afterimage.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)
                    screen.blit(afterimage, (x - camera_x, y - camera_y))

            debug_print(f"Player frame available: {player_anim.get_frame() is not None}")
            if frame := player_anim.get_frame():
                screen.blit(frame, (player.x - camera_x, player.y - camera_y))
            else:
                debug_print("No player frame, drawing green rectangle")
                pygame.draw.rect(screen, (0, 255, 0), (player.x - camera_x, player.y - camera_y, player.width, player.height))
            name_surface = font.render(nickname, True, (255, 255, 255))
            name_rect = name_surface.get_rect(center=(player.x - camera_x + player.width / 2, player.y - camera_y - 10))
            screen.blit(name_surface, name_rect)

            for other_nick, other_data in (mp_client.get_other_players().items() if mp_client else {}):
                other_x = other_data["x"]
                other_y = other_data["y"]
                state = other_data.get("state", "idle")
                direction = other_data.get("direction", "down")
                current_frame = other_data.get("current_frame", 0)
                afterimages = other_data.get("afterimages", [])
                for x, y, alpha, time in afterimages:
                    if time > 0:
                        frames = mp_client.animations.get('run', {}).get(direction, [])
                        if frames:
                            afterimage = frames[current_frame].copy()
                            afterimage.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)
                            screen.blit(afterimage, (x - camera_x, y - camera_y))
                frames = mp_client.animations.get(state if state != 'dodge' else 'run', {}).get(direction, [])
                if frames:
                    frame = frames[current_frame]
                    if state == 'dodge':
                        frame = frame.copy()
                        frame.fill((255, 255, 255, 128), special_flags=pygame.BLEND_RGBA_MULT)
                    screen.blit(frame, (other_x - camera_x, other_y - camera_y))
                else:
                    pygame.draw.rect(screen, (0, 0, 255), (other_x - camera_x, other_y - camera_y, player.width, player.height))
                name_surface = font.render(other_nick, True, (255, 255, 255))
                name_rect = name_surface.get_rect(center=(other_x - camera_x + player.width / 2, other_y - camera_y - 10))
                screen.blit(name_surface, name_rect)

            canvas.style.display = "none"
            canvas.style.display = "block"
            pygame.display.update()
            debug_print(f"Frame {frame_count} rendered")
            frame_count += 1
            clock.tick(60)
            await asyncio.sleep(0.016)
        except Exception as e:
            print(f"Error in game loop: {e}")

    js_document.removeEventListener("keydown", create_proxy(on_keydown))
    js_document.removeEventListener("keyup", create_proxy(on_keyup))
    canvas.removeEventListener("click", create_proxy(on_canvas_click))

asyncio.ensure_future(game_loop())