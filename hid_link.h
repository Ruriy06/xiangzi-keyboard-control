/*
 * hid_link.h —— LYDR_auto6「去特征」通信抽象层（阶段 C-4）
 *
 * 把 .ino 里所有 Serial. 收发统一改名成 Link.，由本头文件按构建形态选底层通道：
 *
 *   CDC_MODE=on（开发形态）
 *       → Link 直接就是 CDC 的 Serial，行为与改造前完全一致，
 *         现成桌面程序仍旧用 COM 口联调。
 *
 *   CDC_MODE=off（最终形态，编译参数 -DCDC_DISABLED）
 *       → Link 是走 HID 的通道，设备不再有 COM 口：
 *           下行  主机→设备：HID Feature report, SET_REPORT(Feature, ID=3)
 *           上行  设备→主机：HID 输入报告,   SendReport(ID=4) 走中断 IN
 *         两个方向本质上都是「字节流」：主机侧忽略 NUL 填充、按 '\n' 切行，
 *         与原来的串口文本协议同构，桌面端只需换后端。
 *
 * 依赖的机制（均已从共享 Arduino 核心源码确认，不修改核心）：
 *   - HID_::setup() 对 SET_REPORT 会落空并返回 false，
 *     PluggableUSB_::setup() 于是继续调用本文件里「0 接口」的 PluggableUSBModule。
 *   - 上行用 HID_::SendReport()，走中断 IN，由主机轮询读取。
 *
 * ⚠ 本文件只在 CDC 关闭时才引入 HID 相关头/全局对象；
 *    CDC 打开时只做一句 #define，绝不引入任何额外符号。
 */
#pragma once

#include <Arduino.h>

#if !defined(CDC_DISABLED)

// ───────────────────── 开发形态：Link 就是 CDC Serial ─────────────────────
#define Link Serial

#else  // CDC_DISABLED

// ───────────────────── 最终形态：走 HID Feature report ─────────────────────
#include <HID.h>
#include <PluggableUSB.h>
#include <USBAPI.h>

#define HID_LINK_ID_DOWN    3     // Feature 报告 ID：主机 → 设备
#define HID_LINK_ID_UP      4     // Input   报告 ID：设备 → 主机
#define HID_LINK_REPORT_LEN 63    // 每个报告的数据字节数（不含报告 ID 字节）
#define HID_LINK_RX_CAP     128   // 接收环形缓冲容量（2 的幂）
#define HID_LINK_TX_CAP     128   // 发送行缓冲容量（须 >= 一行最大长度）

// ── 通道：仿 Stream，可直接替换 Serial 的用法 ────────────────────
class HidLink : public Stream {
public:
  void begin(unsigned long) {}
  void end() {}

  // ── Stream 接口 ───────────────────────────────────────────
  int available() override {
    return (int)((uint8_t)(_rxHead - _rxTail) % HID_LINK_RX_CAP);
  }

  int read() override {
    if (_rxHead == _rxTail) return -1;
    uint8_t c = _rx[_rxTail];
    _rxTail = (uint8_t)((_rxTail + 1) % HID_LINK_RX_CAP);
    return c;
  }

  int peek() override {
    if (_rxHead == _rxTail) return -1;
    return _rx[_rxTail];
  }

  void flush() override { _flushLine(); }

  // ── Print 接口（print/println 的最终落点）──────────────────
  size_t write(uint8_t c) override {
    if (c == 0) return 1;                 // 忽略 NUL（下行填充）
    if (c == '\n') {
      if (_txLen < HID_LINK_TX_CAP) _tx[_txLen++] = '\n';
      _flushLine();
      return 1;
    }
    _tx[_txLen++] = c;
    if (_txLen >= HID_LINK_TX_CAP) _flushLine();
    return 1;
  }

  size_t write(const uint8_t* buf, size_t n) override {
    for (size_t i = 0; i < n; i++) write(buf[i]);
    return n;
  }

  int availableForWrite() { return HID_LINK_REPORT_LEN; }

  // 供 loop() 调用；本实现发送是即时的，保留此钩子以便将来改成轮询式。
  void poll() {}

  // ── 由 PluggableUSB 模块在收到 Feature 报告时投递字节 ────────
  void pushRx(const uint8_t* p, uint8_t n) {
    for (uint8_t i = 0; i < n; i++) {
      if (p[i] == 0) continue;            // 忽略 NUL 填充
      uint8_t next = (uint8_t)((_rxHead + 1) % HID_LINK_RX_CAP);
      if (next == _rxTail) break;         // 缓冲满：丢弃
      _rx[_rxHead] = p[i];
      _rxHead = next;
    }
  }

private:
  void _flushLine() {
    if (_txLen == 0) return;
    uint8_t off = 0;
    while (off < _txLen) {
      uint8_t n = _txLen - off;
      if (n > HID_LINK_REPORT_LEN) n = HID_LINK_REPORT_LEN;
      uint8_t blk[HID_LINK_REPORT_LEN];
      memset(blk, 0, sizeof(blk));
      memcpy(blk, _tx + off, n);
      // 总是发整条报告（NUL 填充）：不依赖 Windows 是否会把短包补齐。
      HID().SendReport(HID_LINK_ID_UP, blk, HID_LINK_REPORT_LEN);
      off += n;
    }
    _txLen = 0;
  }

  volatile uint8_t _rxHead = 0;
  volatile uint8_t _rxTail = 0;
  uint8_t _rx[HID_LINK_RX_CAP];

  uint8_t _tx[HID_LINK_TX_CAP];
  uint8_t _txLen = 0;
};

// 全局唯一实例：.ino 里把 Serial. 改成 Link. 即可。
static HidLink Link;

// ── 厂商自定义报告描述符：ID=3 Feature / ID=4 Input ──────────────
static const uint8_t _hidLinkReportDescriptor[] PROGMEM = {
  0x06, 0x00, 0xFF,   // Usage Page (Vendor Defined 0xFF00)
  0x09, 0x01,         // Usage (0x01)
  0xA1, 0x01,         // Collection (Application)

  0x85, 0x03,         //   Report ID (3)
  0x09, 0x02,         //   Usage (0x02)
  0x15, 0x00,         //   Logical Minimum (0)
  0x26, 0xFF, 0x00,   //   Logical Maximum (255)
  0x75, 0x08,         //   Report Size (8)
  0x95, 0x3F,         //   Report Count (63)
  0xB1, 0x02,         //   Feature (Data,Var,Abs)

  0x85, 0x04,         //   Report ID (4)
  0x09, 0x03,         //   Usage (0x03)
  0x15, 0x00,         //   Logical Minimum (0)
  0x26, 0xFF, 0x00,   //   Logical Maximum (255)
  0x75, 0x08,         //   Report Size (8)
  0x95, 0x3F,         //   Report Count (63)
  0x81, 0x02,         //   Input (Data,Var,Abs)

  0xC0                // End Collection
};

static HIDSubDescriptor _hidLinkNode(_hidLinkReportDescriptor,
                                     sizeof(_hidLinkReportDescriptor));

// 在静态初始化阶段挂到 HID 接口上：必须在 USBDevice.attach() 之前，
// 否则主机会先取走报告描述符（setup() 里再挂就晚了）。
struct HidLinkDescriptorAttacher {
  HidLinkDescriptorAttacher() { HID().AppendDescriptor(&_hidLinkNode); }
};
static HidLinkDescriptorAttacher _hidLinkAttacher;

// ── 下行：接管 SET_REPORT(Feature, ID=3) 的「0 接口」模块 ─────────
class HidLinkDownModule : public PluggableUSBModule {
public:
  HidLinkDownModule() : PluggableUSBModule(0, 0, nullptr) {
    // 关键：PluggableUSBModule 的基类构造函数「不会」自动注册。
    // 必须像 HID_::HID_() 那样显式调用 PluggableUSB().plug(this)，
    // 否则本模块不在 rootNode 链上，PluggableUSB_::setup() 永远遍历不到它，
    // SET_REPORT 会一路返回 false → USBCore 走 Stall() → 主机得到
    // 0x1F「设备没有发挥作用」/ hidapi send_feature_report 返回 -1。
    PluggableUSB().plug(this);
  }

protected:
  bool setup(USBSetup& setup) override {
    // 不校验 wIndex：本模块没有自己的接口，请求的 wIndex 指向 HID 接口。
    if (setup.bmRequestType == REQUEST_HOSTTODEVICE_CLASS_INTERFACE &&
        setup.bRequest      == HID_SET_REPORT &&
        setup.wValueH       == HID_REPORT_TYPE_FEATURE &&
        setup.wValueL       == HID_LINK_ID_DOWN &&
        setup.wLength       >  0) {
      // 关键：控制传输的数据阶段必须被「完整」消费（含报告 ID 字节）。
      // 少读一个字节，数据阶段就结束不了 → 主机报 0x1F「设备没有发挥作用」，
      // 且残留字节会污染下一次控制传输。多余的字节即使丢弃也要读掉。
      uint16_t n = setup.wLength;
      uint8_t keep = (n > sizeof(_tmp)) ? sizeof(_tmp) : (uint8_t)n;
      USB_RecvControl(_tmp, keep);
      for (uint16_t left = n - keep; left > 0; ) {
        uint8_t junk[16];
        uint8_t c = (left > sizeof(junk)) ? sizeof(junk) : (uint8_t)left;
        USB_RecvControl(junk, c);
        left -= c;
      }
      // 带报告 ID 的控制传输，数据首字节就是报告 ID，跳过它。
      uint8_t off = (keep > 1 && _tmp[0] == HID_LINK_ID_DOWN) ? 1 : 0;
      if (keep > off) Link.pushRx(_tmp + off, keep - off);
      return true;   // 已处理，避免 USB 栈 STALL 这个控制传输
    }
    return false;
  }

  // 本模块不占接口/端点/描述符/短名，纯粹用于拦截类请求。
  int     getInterface(uint8_t* interfaceCount) override { (void)interfaceCount; return 0; }
  int     getDescriptor(USBSetup& setup) override { (void)setup; return 0; }
  uint8_t getShortName(char* name) override { (void)name; return 0; }

private:
  uint8_t _tmp[1 + HID_LINK_REPORT_LEN];
};

static HidLinkDownModule _hidLinkDown;

#endif  // CDC_DISABLED
