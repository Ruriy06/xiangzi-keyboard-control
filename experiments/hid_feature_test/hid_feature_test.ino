/*
 * hid_feature_test.ino —— LYDR_auto6「去特征」阶段 C-1~C-3 最小验证固件
 *
 * 目的：在「不带 CDC、只有单一 HID 接口」的形态下，单独验证 HID 双向通道，
 *       不掺入任何业务逻辑（键盘/鼠标、命令解析等）。
 *
 * 两条方向（都用固定报告 ID，与现有串口协议同构的纯 ASCII 文本行）：
 *   下行  主机 → 设备：HID Feature report，SET_REPORT(Feature, ID=3)
 *                      由本 sketch 自己的「0 接口」PluggableUSB 模块接管。
 *                      依据：HID_::setup() 对 SET_REPORT 会落空并返回 false，
 *                      PluggableUSB_::setup() 于是继续调用链上的下一个模块。
 *   上行  设备 → 主机：HID 输入报告，HID().SendReport(ID=4, ...) 走中断 IN，
 *                      由主机侧轮询读取（hid_read / ReadFile）。
 *
 * 这条路线的好处：完全不改共享 Arduino 核心源码。
 *
 * 行协议（'\n' 结尾，单行 ≤ 31 字节）：
 *   {PING}        → {PONG}
 *   {ECHO:xxxx}   → {ECHO:xxxx}
 *   其它           → {BAD}
 *
 * 注意：本固件以 -DCDC_DISABLED 构建，烧入后设备不再有 COM 口，
 *       之后只能双击 RESET 手动进 bootloader 才能重烧。
 */

#include <HID.h>
#include <PluggableUSB.h>
#include <USBAPI.h>

#define REPORT_ID_DOWN 3      // Feature：主机 → 设备
#define REPORT_ID_UP   4      // Input  ：设备 → 主机
#define REPORT_LEN     32     // 报告数据长度（不含报告 ID 字节）

// ── 厂商自定义报告描述符 ────────────────────────────────────────
// Report ID 3 = Feature（32 字节）
// Report ID 4 = Input  （32 字节）
static const uint8_t _vendorReportDescriptor[] PROGMEM = {
  0x06, 0x00, 0xFF,   // Usage Page (Vendor Defined 0xFF00)
  0x09, 0x01,         // Usage (0x01)
  0xA1, 0x01,         // Collection (Application)

  0x85, 0x03,         //   Report ID (3)
  0x09, 0x02,         //   Usage (0x02)
  0x15, 0x00,         //   Logical Minimum (0)
  0x26, 0xFF, 0x00,   //   Logical Maximum (255)
  0x75, 0x08,         //   Report Size (8)
  0x95, 0x20,         //   Report Count (32)
  0xB1, 0x02,         //   Feature (Data,Var,Abs)

  0x85, 0x04,         //   Report ID (4)
  0x09, 0x03,         //   Usage (0x03)
  0x15, 0x00,         //   Logical Minimum (0)
  0x26, 0xFF, 0x00,   //   Logical Maximum (255)
  0x75, 0x08,         //   Report Size (8)
  0x95, 0x20,         //   Report Count (32)
  0x81, 0x02,         //   Input (Data,Var,Abs)

  0xC0                // End Collection
};

static HIDSubDescriptor _vendorNode(_vendorReportDescriptor,
                                    sizeof(_vendorReportDescriptor));

// 必须在静态初始化阶段把描述符挂上 HID 接口：
// USBDevice.attach() 在 main() 里 setup() 之前执行，主机会立刻取描述符，
// 放到 setup() 里再 AppendDescriptor 就太晚了。
struct VendorDescriptorAttacher {
  VendorDescriptorAttacher() { HID().AppendDescriptor(&_vendorNode); }
};
static VendorDescriptorAttacher _attacher;   // 先构造 → HID 接口号 0

// ── 下行：接管 SET_REPORT(Feature, ID=3) ────────────────────────
class HidDownlinkModule : public PluggableUSBModule {
public:
  HidDownlinkModule() : PluggableUSBModule(0, 0, nullptr) {}

  // 必须至少容纳一次控制传输的全部字节：wLength = 1（报告 ID）+ 报告长度。
  // 少读一个字节数据阶段就结束不了，主机会报 0x1F「设备没有发挥作用」。
  uint8_t rx[64];
  volatile uint8_t rxLen = 0;
  volatile bool    rxNew = false;

protected:
  bool setup(USBSetup& setup) override {
    // 只认领发往 HID 接口的 SET_REPORT(Feature, ID=3)。
    // 不校验 wIndex：本模块没有自己的接口，请求的 wIndex 指向 HID 的接口。
    if (setup.bmRequestType == REQUEST_HOSTTODEVICE_CLASS_INTERFACE &&
        setup.bRequest      == HID_SET_REPORT &&
        setup.wValueH       == HID_REPORT_TYPE_FEATURE &&
        setup.wValueL       == REPORT_ID_DOWN &&
        setup.wLength       >  0) {
      uint16_t n = setup.wLength;
      uint8_t keep = (n > sizeof(rx)) ? sizeof(rx) : (uint8_t)n;
      USB_RecvControl(rx, keep);
      // 数据阶段必须被完整消费：多余的字节即使不要也要读掉。
      for (uint16_t left = n - keep; left > 0; ) {
        uint8_t junk[16];
        uint8_t c = (left > sizeof(junk)) ? sizeof(junk) : (uint8_t)left;
        USB_RecvControl(junk, c);
        left -= c;
      }
      rxLen = keep;
      rxNew = true;
      return true;   // 已处理（不让 USB 栈 STALL 这个控制传输）
    }
    return false;
  }

  // 本模块不占接口/端点/描述符/短名，纯粹用于拦截类请求。
  int  getInterface(uint8_t* interfaceCount) override { (void)interfaceCount; return 0; }
  int  getDescriptor(USBSetup& setup) override { (void)setup; return 0; }
  uint8_t getShortName(char* name) override { (void)name; return 0; }
};

static HidDownlinkModule _downlink;   // 后构造 → HID 之后

// ── 上行：一行文本打成一个输入报告 ──────────────────────────────
static void sendLine(const char* s) {
  uint8_t buf[REPORT_LEN];
  memset(buf, 0, sizeof(buf));
  uint8_t n = 0;
  while (s[n] && n < REPORT_LEN - 1) { buf[n] = (uint8_t)s[n]; n++; }
  buf[n++] = '\n';
  // 只发 n 字节（USB 允许中断 IN 短包），主机侧按实际长度读取。
  HID().SendReport(REPORT_ID_UP, buf, n);
}

static void handleLine(const char* s) {
  if (strcmp(s, "{PING}") == 0)      { sendLine("{PONG}"); return; }
  if (strncmp(s, "{ECHO:", 6) == 0)  { sendLine(s);        return; }
  sendLine("{BAD}");
}

// ── 行装配 ─────────────────────────────────────────────────────
static char    _line[REPORT_LEN];
static uint8_t _lineLen = 0;

static void feedBytes(const uint8_t* p, uint8_t n) {
  for (uint8_t i = 0; i < n; i++) {
    char c = (char)p[i];
    if (c == '\n' || c == '\r') {
      if (_lineLen) { _line[_lineLen] = 0; handleLine(_line); _lineLen = 0; }
    } else if (_lineLen < REPORT_LEN - 1) {
      _line[_lineLen++] = c;
    }
  }
}

void setup() {
  // 无 CDC，不需要 Serial.begin()。
  sendLine("{BOOT}");
}

void loop() {
  if (_downlink.rxNew) {
    _downlink.rxNew = false;
    uint8_t n = _downlink.rxLen;
    if (n > 0) {
      // 带报告 ID 的控制传输，数据首字节就是报告 ID，跳过它。
      uint8_t off = (_downlink.rx[0] == REPORT_ID_DOWN) ? 1 : 0;
      if (n > off) feedBytes(_downlink.rx + off, n - off);
    }
  }
}
