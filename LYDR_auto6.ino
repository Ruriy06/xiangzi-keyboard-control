// 串口协议: {CMD}\n 一行一条命令, CMD 为指令名
// 例: {TAB} {LEFT_CLICK} {MOVE_100_200} {CTRL+C} {MC_500_300}
#include "Keyboard.h"
#include "Mouse.h"
#include "MouseTo.h"

#define SERIAL_BAUD_RATE    115200
#define MAX_MODIFIERS        3
#define MAX_CMD_LENGTH       64

#define DEF_SCREEN_WIDTH     2560
#define DEF_SCREEN_HEIGHT    1440
#define DEF_KEY_PRESS        100
#define DEF_KEY_HOLD          50
#define DEF_KEY_RELEASE       10
#define DEF_MOUSE_CLICK       50
#define DEF_MOUSE_PRESS       30
#define DEF_MOUSE_MOVE        50
#define DEF_MOUSE_JUMP        80

#define CFG_DELAY_MAX        250
#define CFG_MAX_JUMP_MIN       1
#define CFG_MAX_JUMP_MAX     255
#define CFG_SCREEN_MIN         1
#define CFG_SCREEN_MAX     16384
#define CFG_NORM_MAX        1000

// 鼠标侧键 HID 报告 bitmask (第4/5键), 标准 Mouse.h 未定义
#ifndef MOUSE_BACK
#define MOUSE_BACK            0x08
#endif
#ifndef MOUSE_FORWARD
#define MOUSE_FORWARD         0x10
#endif

struct MouseMap {
  const char* name;
  uint8_t action;
  uint8_t button;
};

int screenW = DEF_SCREEN_WIDTH;
int screenH = DEF_SCREEN_HEIGHT;
uint8_t keyPressDelay = DEF_KEY_PRESS;
uint8_t keyHoldDelay = DEF_KEY_HOLD;
uint8_t keyReleaseDelay = DEF_KEY_RELEASE;
uint8_t mouseClickDelay = DEF_MOUSE_CLICK;
uint8_t mousePressDelay = DEF_MOUSE_PRESS;
uint8_t mouseMoveDelay = DEF_MOUSE_MOVE;
uint8_t mouseMaxJump = DEF_MOUSE_JUMP;
bool stopFlag = false;

char cmdBuffer[MAX_CMD_LENGTH];
uint8_t cmdLen = 0;

struct KeyMap {
  const char* name;
  uint8_t code;
  bool isModifier;
};

const KeyMap keyMap[] PROGMEM = {
  {"CTRL", KEY_LEFT_CTRL, true},
  {"SHIFT", KEY_LEFT_SHIFT, true},
  {"ALT", KEY_LEFT_ALT, true},
  {"WIN", KEY_LEFT_GUI, true},
  {"ESC", KEY_ESC, false},
  {"TAB", KEY_TAB, false},
  {"ENTER", KEY_RETURN, false},
  {"SPACE", ' ', false},
  {"BACKSPACE", KEY_BACKSPACE, false},
  {"CAPS_LOCK", KEY_CAPS_LOCK, false},
  {"DELETE", KEY_DELETE, false},
  {"INSERT", KEY_INSERT, false},
  {"HOME", KEY_HOME, false},
  {"END", KEY_END, false},
  {"PAGE_UP", KEY_PAGE_UP, false},
  {"PAGE_DOWN", KEY_PAGE_DOWN, false},
  {"PRINT_SCREEN", KEY_PRINT_SCREEN, false},
  {"SCROLL_LOCK", KEY_SCROLL_LOCK, false},
  {"PAUSE", KEY_PAUSE, false},
  {"MENU", 0xED, false},  // HID Application/Menu 键，Arduino Keyboard.h 未定义名称
  {"GRAVE", '`', false},
  {"MINUS", '-', false},
  {"EQUAL", '=', false},
  {"LBRACKET", '[', false},
  {"RBRACKET", ']', false},
  {"BACKSLASH", '\\', false},
  {"SEMICOLON", ';', false},
  {"QUOTE", '\'', false},
  {"COMMA", ',', false},
  {"PERIOD", '.', false},
  {"SLASH", '/', false},
  {"UP", KEY_UP_ARROW, false},
  {"DOWN", KEY_DOWN_ARROW, false},
  {"LEFT", KEY_LEFT_ARROW, false},
  {"RIGHT", KEY_RIGHT_ARROW, false},
  {"F1", KEY_F1, false},{"F2", KEY_F2, false},{"F3", KEY_F3, false},
  {"F4", KEY_F4, false},{"F5", KEY_F5, false},{"F6", KEY_F6, false},
  {"F7", KEY_F7, false},{"F8", KEY_F8, false},{"F9", KEY_F9, false},
  {"F10", KEY_F10, false},{"F11", KEY_F11, false},{"F12", KEY_F12, false}
};
const uint8_t keyMapSize = sizeof(keyMap) / sizeof(KeyMap);

const MouseMap mouseMap[] PROGMEM = {
  {"LEFT_CLICK", 0, MOUSE_LEFT}, {"LEFT_PRESS", 1, MOUSE_LEFT}, {"LEFT_RELEASE", 2, MOUSE_LEFT},
  {"RIGHT_CLICK", 0, MOUSE_RIGHT}, {"RIGHT_PRESS", 1, MOUSE_RIGHT}, {"RIGHT_RELEASE", 2, MOUSE_RIGHT},
  {"MIDDLE_CLICK", 0, MOUSE_MIDDLE}, {"MIDDLE_PRESS", 1, MOUSE_MIDDLE}, {"MIDDLE_RELEASE", 2, MOUSE_MIDDLE}
};
const uint8_t mouseMapSize = sizeof(mouseMap) / sizeof(MouseMap);

void releaseAll() {
  Keyboard.releaseAll();
  Mouse.release(MOUSE_LEFT);
  Mouse.release(MOUSE_RIGHT);
  Mouse.release(MOUSE_MIDDLE);
}

void resetConfig() {
  screenW = DEF_SCREEN_WIDTH;
  screenH = DEF_SCREEN_HEIGHT;
  keyPressDelay = DEF_KEY_PRESS;
  keyHoldDelay = DEF_KEY_HOLD;
  keyReleaseDelay = DEF_KEY_RELEASE;
  mouseClickDelay = DEF_MOUSE_CLICK;
  mousePressDelay = DEF_MOUSE_PRESS;
  mouseMoveDelay = DEF_MOUSE_MOVE;
  mouseMaxJump = DEF_MOUSE_JUMP;
  MouseTo.setScreenResolution(screenW, screenH);
  MouseTo.setMaxJump(mouseMaxJump);
}

void sendError(const char* code) {
  Serial.print("{ERR:");
  Serial.print(code);
  Serial.println("}");
}

void sendConfig() {
  Serial.print("{CFG:SCREEN=");
  Serial.print(screenW);
  Serial.print("x");
  Serial.print(screenH);
  Serial.println("}");
  Serial.print("{CFG:KEY_PRESS_BASE=");
  Serial.print(keyPressDelay);
  Serial.println("}");
  Serial.println("{CFG:KEY_PRESS_JITTER=-5..5}");
  Serial.print("{CFG:KEY_RELEASE_BASE=");
  Serial.print(keyReleaseDelay);
  Serial.println("}");
  Serial.println("{CFG:KEY_RELEASE_JITTER=-3..3}");
  Serial.print("{CFG:COMBO_MODIFIER_HOLD=");
  Serial.print(keyHoldDelay);
  Serial.println("}");
  Serial.print("{CFG:MOUSE_PRESS_BASE=");
  Serial.print(mousePressDelay);
  Serial.println("}");
  Serial.print("{CFG:MOUSE_CLICK_GAP=");
  Serial.print(mouseClickDelay);
  Serial.println("}");
  Serial.print("{CFG:MOUSE_MOVE_GAP=");
  Serial.print(mouseMoveDelay);
  Serial.println("}");
  Serial.print("{CFG:MOUSE_MAX_JUMP=");
  Serial.print(mouseMaxJump);
  Serial.println("}");
  Serial.println("{CFG:MC_TIMING=PRESS_10..30,GAP_20..40}");
  Serial.println("{CFG:MCR_TIMING=PRESS_30..50,GAP_40..80}");
}

bool parseIntStrict(const char* text, int& value) {
  if (text == nullptr || *text == '\0') return false;
  char* end = nullptr;
  long parsed = strtol(text, &end, 10);
  if (*end != '\0' || parsed < -32768 || parsed > 32767) return false;
  value = (int)parsed;
  return true;
}

bool parseIntPair(const char* text, int& first, int& second) {
  if (text == nullptr || *text == '\0') return false;
  char* separator = nullptr;
  long firstValue = strtol(text, &separator, 10);
  if (separator == text || *separator != '_') return false;
  char* end = nullptr;
  long secondValue = strtol(separator + 1, &end, 10);
  if (*end != '\0' || firstValue < -32768 || firstValue > 32767 || secondValue < -32768 || secondValue > 32767) return false;
  first = (int)firstValue;
  second = (int)secondValue;
  return true;
}

bool setConfigValue(const char* cmd, const char* prefix, uint8_t& setting, int minValue, int maxValue) {
  size_t prefixLength = strlen(prefix);
  if (strncmp(cmd, prefix, prefixLength) != 0) return false;

  int value = 0;
  if (!parseIntStrict(cmd + prefixLength, value) || value < minValue || value > maxValue) {
    sendError("CFG_VALUE");
    return true;
  }

  setting = (uint8_t)value;
  Serial.println("{OK:CFG}");
  return true;
}

void handleConfigCommand(const char* cmd) {
  if (strcmp(cmd, "CFG_GET") == 0) {
    sendConfig();
  } else if (strcmp(cmd, "CFG_RESET") == 0) {
    resetConfig();
    Serial.println("{OK:CFG_RESET}");
  } else if (setConfigValue(cmd, "CFG_KEY_PRESS_", keyPressDelay, 0, CFG_DELAY_MAX)) {
  } else if (setConfigValue(cmd, "CFG_KEY_RELEASE_", keyReleaseDelay, 0, CFG_DELAY_MAX)) {
  } else if (setConfigValue(cmd, "CFG_COMBO_HOLD_", keyHoldDelay, 0, CFG_DELAY_MAX)) {
  } else if (setConfigValue(cmd, "CFG_MOUSE_PRESS_", mousePressDelay, 0, CFG_DELAY_MAX)) {
  } else if (setConfigValue(cmd, "CFG_MOUSE_CLICK_", mouseClickDelay, 0, CFG_DELAY_MAX)) {
  } else if (setConfigValue(cmd, "CFG_MOUSE_MOVE_", mouseMoveDelay, 0, CFG_DELAY_MAX)) {
  } else if (strncmp(cmd, "CFG_MAX_JUMP_", 13) == 0) {
    int value = 0;
    if (!parseIntStrict(cmd + 13, value) || value < CFG_MAX_JUMP_MIN || value > CFG_MAX_JUMP_MAX) {
      sendError("CFG_VALUE");
    } else {
      mouseMaxJump = (uint8_t)value;
      MouseTo.setMaxJump(mouseMaxJump);
      Serial.println("{OK:CFG}");
    }
  } else {
    sendError("CFG_CMD");
  }
}

void handleScreenCommand(const char* cmd) {
  if (strcmp(cmd, "SCR_GET") == 0) {
    Serial.print("{SCR:");
    Serial.print(screenW);
    Serial.print("x");
    Serial.print(screenH);
    Serial.println("}");
    return;
  }

  int width = 0;
  int height = 0;
  if (!parseIntPair(cmd + 4, width, height) || width < CFG_SCREEN_MIN || width > CFG_SCREEN_MAX || height < CFG_SCREEN_MIN || height > CFG_SCREEN_MAX) {
    sendError("SCR_VALUE");
    return;
  }

  screenW = width;
  screenH = height;
  MouseTo.setScreenResolution(screenW, screenH);
  Serial.println("{OK:SCR}");
}

void delayWithJitter(int baseDelay, int minJitter, int maxJitter) {
  int totalDelay = baseDelay + random(minJitter, maxJitter + 1);
  if (totalDelay < 0) totalDelay = 0;
  delay(totalDelay);
}

// Arduino Keyboard 会把 ASCII 大写字母解释成 Shift+字母。
// 游戏按键不区分大小写，因此统一使用小写字母，避免 W/A/S/D 等按键隐式触发 Shift。
uint8_t normalizeLetterKey(uint8_t code) {
  if (code >= 'A' && code <= 'Z') return code + ('a' - 'A');
  return code;
}

// 修饰键(CTRL/SHIFT/ALT/WIN): 按下不释放, 由 releaseAll() 统一释放
// 普通键: 按下→延迟→释放
void pressKey(uint8_t code, bool isModifier) {
  if (!isModifier) code = normalizeLetterKey(code);
  Keyboard.press(code);
  if (!isModifier) {
    delayWithJitter(keyPressDelay, -5, 5);  // ±5ms 微抖动
    Keyboard.release(code);
    delayWithJitter(keyReleaseDelay, -3, 3);
  }
}

// 解析组合键如 "CTRL+SHIFT+TAB": 修饰键先按下, 主键按下后统一释放
void handleKeyCombo(const char* combo) {
  uint8_t modifiers[MAX_MODIFIERS] = {0};
  uint8_t modCount = 0;
  uint8_t mainKey = 0;
  char part[16] = {0};
  uint8_t partLen = 0;

  for (uint8_t i = 0; combo[i] != '\0'; i++) {
    if (combo[i] == '+' || combo[i+1] == '\0') {
      if (combo[i+1] == '\0') part[partLen++] = combo[i];
      part[partLen] = '\0';

      for (uint8_t j = 0; j < keyMapSize; j++) {
        if (strcmp(part, (const char*)pgm_read_word(&keyMap[j].name)) == 0) {
          if (pgm_read_byte(&keyMap[j].isModifier) && modCount < MAX_MODIFIERS) {
            modifiers[modCount++] = pgm_read_byte(&keyMap[j].code);
          } else {
            mainKey = pgm_read_byte(&keyMap[j].code);
          }
          break;
        }
      }
      if (mainKey == 0 && partLen == 1) mainKey = part[0];
      partLen = 0;
      memset(part, 0, sizeof(part));
    } else {
      if (partLen < 15) part[partLen++] = combo[i];
    }
  }

  for (uint8_t i = 0; i < modCount; i++) Keyboard.press(modifiers[i]);
  delay(keyHoldDelay);
  if (mainKey) pressKey(mainKey, false);
  releaseAll();
}

void mouseClick(uint8_t btn) {
  Mouse.press(btn);
  delay(mousePressDelay);
  Mouse.release(btn);
  delay(mouseClickDelay);
}

// 绝对坐标移动: MouseTo 内部追踪光标位置, 分步跳转(mouseMaxJump px/步)
void mouseMoveTo(int x, int y) {
  x = constrain(x, 0, screenW);
  y = constrain(y, 0, screenH);
  MouseTo.setTarget(x, y);
  while (!MouseTo.move() && !stopFlag) delay(random(2, 9));
  delay(mouseMoveDelay);
}

// MC_x_y / MC_NORM_x_y 共用的快速绝对移动+左键点击，保持原有独立随机时序
void mouseMoveAndClickFast(int x, int y) {
  x = constrain(x, 0, screenW);
  y = constrain(y, 0, screenH);
  MouseTo.setTarget(x, y);
  while (!MouseTo.move() && !stopFlag) delay(random(2, 9));
  Mouse.press(MOUSE_LEFT);
  delay(random(10, 30));
  Mouse.release(MOUSE_LEFT);
  delay(random(20, 40));
}

// 大角度转向专用: 一条串口命令内快速完成大幅相对移动, 避免多命令排队导致转向滞后
void mouseTurnRelative(int dx, int dy) {
  while ((dx != 0 || dy != 0) && !stopFlag) {
    int sx = constrain(dx, -127, 127);
    int sy = constrain(dy, -127, 127);
    Mouse.move(sx, sy);
    dx -= sx;
    dy -= sy;
    delay(1);
  }
}

// 已弃用: 原通过 PROGMEM mouseMap 查表, 改用显式 strcmp 避免指针问题
void handleMouseCommand(const char* cmd) {
  for (uint8_t i = 0; i < mouseMapSize; i++) {
    if (strcmp(cmd, (const char*)pgm_read_word(&mouseMap[i].name)) == 0) {
      uint8_t action = pgm_read_byte(&mouseMap[i].action);
      uint8_t btn = pgm_read_byte(&mouseMap[i].button);
      if (action == 0) mouseClick(btn);
      else if (action == 1) Mouse.press(btn);
      else if (action == 2) Mouse.release(btn);
      return;
    }
  }
}

void handleMouseMove(const char* cmd) {
  if (strcmp(cmd, "MOVE_CENTER") == 0) mouseMoveTo(screenW/2, screenH/2);
  else if (strcmp(cmd, "MOVE_TOP_LEFT") == 0) mouseMoveTo(0,0);
  // 先匹配更长前缀，防止被 MOVE_ 的短前缀劫持
  else if (strncmp(cmd, "MOVE_NORM_", 10) == 0) {
    int x = 0;
    int y = 0;
    if (!parseIntPair(cmd + 10, x, y) || x < 0 || x > CFG_NORM_MAX || y < 0 || y > CFG_NORM_MAX) {
      sendError("NORM_VALUE");
    } else {
      mouseMoveTo((int)((long)screenW * x / CFG_NORM_MAX), (int)((long)screenH * y / CFG_NORM_MAX));
    }
  } else if (strncmp(cmd, "MOVE_REL_", 9) == 0) {
    char* underscore = strchr(cmd+9, '_');
    if (underscore != nullptr) {
      int dx = atoi(cmd+9);
      int dy = atoi(underscore + 1);
      Mouse.move(dx, dy);
      delay(mouseMoveDelay);
    }
  } else if (strncmp(cmd, "TURN_REL_", 9) == 0) {
    char* underscore = strchr(cmd+9, '_');
    if (underscore != nullptr) {
      int dx = atoi(cmd+9);
      int dy = atoi(underscore + 1);
      mouseTurnRelative(dx, dy);
    }
  } else if (strncmp(cmd, "MOVE_", 5) == 0) {
    char* underscore = strchr(cmd+5, '_');
    if (underscore != nullptr) {
      int x = atoi(cmd+5);
      int y = atoi(underscore + 1);
      mouseMoveTo(x, y);
    }
  }
}

unsigned long lastCmdTime = 0;
#define CMD_TIMEOUT_MS 30000

void setup() {
  Keyboard.begin();
  Mouse.begin();
  Serial.begin(SERIAL_BAUD_RATE);
  resetConfig();
  lastCmdTime = millis();
  delay(500);
}

// 计算 XOR 校验和
uint8_t xorChecksum(const char* s, uint8_t len) {
  uint8_t chk = 0;
  for (uint8_t i = 0; i < len; i++) chk ^= s[i];
  return chk;
}

void loop() {
  // 超时安全: 30秒无有效指令自动释放所有按键
  if (millis() - lastCmdTime > CMD_TIMEOUT_MS) {
    releaseAll();
    stopFlag = true;
  }

  while (Serial.available()) {
    char c = Serial.read();
    lastCmdTime = millis();  // 有串口数据就刷新, 防止正常间隔触发超时
    if (c == '\n' || c == '\r') {
      if (cmdLen > 0) {
        cmdBuffer[cmdLen] = '\0';
        // 校验和: {CMD}#CHK 格式, CHK 为2位十六进制 XOR
        char* hashPos = strchr(cmdBuffer, '#');
        bool checksumOK = true;
        if (hashPos != nullptr) {
          *hashPos = '\0';  // 截断, cmdBuffer 现在是 {CMD}
          char* chkStr = hashPos + 1;
          if (strlen(chkStr) >= 2) {
            uint8_t expected = strtol(chkStr, nullptr, 16);
            // 计算 {CMD} 部分 (不含花括号) 的 XOR
            uint8_t actual = xorChecksum(cmdBuffer + 1, strlen(cmdBuffer) - 2);
            checksumOK = (expected == actual);
          }
          if (!checksumOK) {
            Serial.println("{NACK}");
            cmdLen = 0; memset(cmdBuffer, 0, sizeof(cmdBuffer));
            continue;
          }
        }
        // 解析 {} 包裹的命令
        if (cmdBuffer[0] == '{' && (hashPos ? hashPos[-1] == '}' : cmdBuffer[strlen(cmdBuffer)-1] == '}')) {
          char* endBrace = hashPos ? hashPos - 1 : cmdBuffer + strlen(cmdBuffer) - 1;
          *endBrace = '\0';
          char* cmd = cmdBuffer + 1;
          stopFlag = false;
          lastCmdTime = millis();
          Serial.print("CMD:");
          Serial.println(cmd);

          // 命令分发: 优先匹配前缀(MC_/MCR_/MOVE) 和全名, 最后回退到 keyMap

          if (strstr(cmd, "+") != nullptr) handleKeyCombo(cmd);
          else if (strncmp(cmd, "CFG_", 4) == 0) handleConfigCommand(cmd);
          else if (strncmp(cmd, "SCR_", 4) == 0) handleScreenCommand(cmd);
          // MC_NORM_x_y: 按当前屏幕尺寸换算 0~1000 的比例坐标后移动+点击
          else if (strncmp(cmd, "MC_NORM_", 8) == 0) {
            int x = 0;
            int y = 0;
            if (!parseIntPair(cmd + 8, x, y) || x < 0 || x > CFG_NORM_MAX || y < 0 || y > CFG_NORM_MAX) {
              sendError("NORM_VALUE");
            } else {
              mouseMoveAndClickFast((int)((long)screenW * x / CFG_NORM_MAX), (int)((long)screenH * y / CFG_NORM_MAX));
            }
          }
          // MC_x_y: 绝对移动+点击, 省去 mouseMoveDelay/mouseClickDelay, 保持原有独立快速时序
          else if (strncmp(cmd, "MC_", 3) == 0) {
            char* underscore = strchr(cmd+3, '_');
            if (underscore != nullptr) {
              int x = atoi(cmd+3);
              int y = atoi(underscore + 1);
              mouseMoveAndClickFast(x, y);
            }
          }
          // MCR_dx_dy: 相对移动+点击
          else if (strncmp(cmd, "MCR_", 4) == 0) {
            char* underscore = strchr(cmd+4, '_');
            if (underscore != nullptr) {
              int dx = atoi(cmd+4);
              int dy = atoi(underscore + 1);
              while ((dx != 0 || dy != 0) && !stopFlag) {
                int sx = constrain(dx, -127, 127);
                int sy = constrain(dy, -127, 127);
                Mouse.move(sx, sy);
                dx -= sx;
                dy -= sy;
                delay(random(2, 9));
              }
              Mouse.press(MOUSE_LEFT);
              delay(random(30, 50));
              Mouse.release(MOUSE_LEFT);
              delay(random(40, 80));
            }
          }
          // KEY_DOWN_X / KEY_UP_X: 通用按键按住/释放, 支持单字符(W)和命名键(TAB/ESC/F1等)
          else if (strncmp(cmd, "KEY_DOWN_", 9) == 0) {
            const char* key = cmd + 9;
            if (strlen(key) == 1) Keyboard.press(normalizeLetterKey(key[0]));
            else for (uint8_t i = 0; i < keyMapSize; i++)
              if (strcmp(key, (const char*)pgm_read_word(&keyMap[i].name)) == 0)
                { Keyboard.press(pgm_read_byte(&keyMap[i].code)); break; }
          }
          else if (strncmp(cmd, "KEY_UP_", 7) == 0) {
            const char* key = cmd + 7;
            if (strlen(key) == 1) Keyboard.release(normalizeLetterKey(key[0]));
            else for (uint8_t i = 0; i < keyMapSize; i++)
              if (strcmp(key, (const char*)pgm_read_word(&keyMap[i].name)) == 0)
                { Keyboard.release(pgm_read_byte(&keyMap[i].code)); break; }
          }
          else if (strncmp(cmd, "TURN_REL_", 9) == 0) handleMouseMove(cmd);
          else if (strstr(cmd, "MOVE") != nullptr) handleMouseMove(cmd);
          else if (strcmp(cmd, "LEFT_CLICK") == 0) mouseClick(MOUSE_LEFT);
          else if (strcmp(cmd, "LEFT_PRESS") == 0) Mouse.press(MOUSE_LEFT);
          else if (strcmp(cmd, "LEFT_RELEASE") == 0) Mouse.release(MOUSE_LEFT);
          else if (strcmp(cmd, "RIGHT_CLICK") == 0) mouseClick(MOUSE_RIGHT);
          else if (strcmp(cmd, "RIGHT_PRESS") == 0) Mouse.press(MOUSE_RIGHT);
          else if (strcmp(cmd, "RIGHT_RELEASE") == 0) Mouse.release(MOUSE_RIGHT);
          else if (strcmp(cmd, "BACK_CLICK") == 0) mouseClick(MOUSE_BACK);
          else if (strcmp(cmd, "BACK_PRESS") == 0) Mouse.press(MOUSE_BACK);
          else if (strcmp(cmd, "BACK_RELEASE") == 0) Mouse.release(MOUSE_BACK);
          else if (strcmp(cmd, "FORWARD_CLICK") == 0) mouseClick(MOUSE_FORWARD);
          else if (strcmp(cmd, "FORWARD_PRESS") == 0) Mouse.press(MOUSE_FORWARD);
          else if (strcmp(cmd, "FORWARD_RELEASE") == 0) Mouse.release(MOUSE_FORWARD);

          // 鼠标滚轮控制（标准库唯一正确写法）
          else if (strncmp(cmd, "WHEEL_", 6) == 0) {
            int wheel = atoi(cmd + 6);
            if (wheel > 127) wheel = 127;
            if (wheel < -127) wheel = -127;
            Mouse.move(0, 0, (signed char)wheel);
            delay(10);
          }

          else if (strcmp(cmd, "STOP") == 0) { stopFlag = true; releaseAll(); }
          else if (strncmp(cmd, "WAIT_", 5) == 0) delay(atoi(cmd+5));
          else {
            // 常用键显式 strcmp 避免 PROGMEM 指针问题; 冷门键(F1~F12/修饰键)才走 keyMap 回退
            if (strcmp(cmd, "TAB") == 0) pressKey(KEY_TAB, false);
            else if (strcmp(cmd, "ESC") == 0) pressKey(KEY_ESC, false);
            else if (strcmp(cmd, "SPACE") == 0) pressKey(' ', false);
            else if (strcmp(cmd, "ENTER") == 0) pressKey(KEY_RETURN, false);
            else if (strcmp(cmd, "BACKSPACE") == 0) pressKey(KEY_BACKSPACE, false);
            else if (strcmp(cmd, "UP") == 0) pressKey(KEY_UP_ARROW, false);
            else if (strcmp(cmd, "DOWN") == 0) pressKey(KEY_DOWN_ARROW, false);
            else if (strcmp(cmd, "LEFT") == 0) pressKey(KEY_LEFT_ARROW, false);
            else if (strcmp(cmd, "RIGHT") == 0) pressKey(KEY_RIGHT_ARROW, false);
            else {
              for (uint8_t i = 0; i < keyMapSize; i++) {
                if (strcmp(cmd, (const char*)pgm_read_word(&keyMap[i].name)) == 0) {
                  pressKey(pgm_read_byte(&keyMap[i].code), pgm_read_byte(&keyMap[i].isModifier));
                  goto endParse;
                }
              }
              if (strlen(cmd) == 1) pressKey(cmd[0], false);
            }
          }
          endParse:
          cmdLen = 0;
          memset(cmdBuffer, 0, sizeof(cmdBuffer));
        } else {
          Serial.print("BAD:");
          Serial.println(cmdBuffer);
          cmdLen = 0;
          memset(cmdBuffer, 0, sizeof(cmdBuffer));
        }
      }
    } else if (cmdLen < MAX_CMD_LENGTH - 1) {
      cmdBuffer[cmdLen++] = c;
    }
  }
}
