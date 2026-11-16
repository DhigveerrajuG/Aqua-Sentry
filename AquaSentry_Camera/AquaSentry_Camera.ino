/**
 * ============================================================================
 * Project: Aqua-Sentry Vision & Teleoperation Subsystem (ESP32-CAM)
 * Target Hardware: AI-Thinker ESP32-CAM (OV2640)
 * 
 * Functionality:
 *   - Standalone Wi-Fi Access Point ("AquaSentry-Vision", 192.168.4.1).
 *   - Low-latency MJPEG video server on port 81.
 *   - Interactive Web Teleoperation Control Interface on port 80.
 *   - HTTP Command API (/control?cmd=...) for browser & Python laptop teleop.
 *   - UART Bridge to Arduino Uno for steering, mode switching, and E-Stop.
 * ============================================================================
 */

#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"

// ==========================================
// WI-FI ACCESS POINT CREDENTIALS
// ==========================================
const char* AP_SSID = "AquaSentry-Vision";
const char* AP_PASS = "aquasentry123";

// ==========================================
// CAMERA PIN CONFIGURATION (AI-THINKER MODEL)
// ==========================================
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// HTTP Server Handles
httpd_handle_t stream_httpd = NULL;
httpd_handle_t index_httpd  = NULL;

#define PART_BOUNDARY "123456789000000000000987654321"
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

// ==========================================
// MJPEG VIDEO STREAM HANDLER (PORT 81)
// ==========================================
static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t * fb = NULL;
  esp_err_t res = ESP_OK;
  size_t _jpg_buf_len = 0;
  uint8_t * _jpg_buf = NULL;
  char part_buf[64];

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if (res != ESP_OK) return res;

  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      res = ESP_FAIL;
      break;
    }

    if (fb->format != PIXFORMAT_JPEG) {
      bool jpeg_converted = frame2jpg(fb, 80, &_jpg_buf, &_jpg_buf_len);
      esp_camera_fb_return(fb);
      fb = NULL;
      if (!jpeg_converted) {
        res = ESP_FAIL;
        break;
      }
    } else {
      _jpg_buf_len = fb->len;
      _jpg_buf = fb->buf;
    }

    if (res == ESP_OK) {
      size_t hlen = snprintf(part_buf, sizeof(part_buf), _STREAM_PART, _jpg_buf_len);
      res = httpd_resp_send_chunk(req, part_buf, hlen);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    }

    if (fb) {
      esp_camera_fb_return(fb);
      fb = NULL;
      _jpg_buf = NULL;
    } else if (_jpg_buf) {
      free(_jpg_buf);
      _jpg_buf = NULL;
    }

    if (res != ESP_OK) break;
  }
  return res;
}

// ==========================================
// HTTP CONTROL API HANDLER (/control?cmd=...)
// ==========================================
static esp_err_t control_handler(httpd_req_t *req) {
  char*  buf;
  size_t buf_len;
  char cmd_val[16] = {0};

  buf_len = httpd_req_get_url_query_len(req) + 1;
  if (buf_len > 1) {
    buf = (char*)malloc(buf_len);
    if (httpd_req_get_url_query_str(req, buf, buf_len) == ESP_OK) {
      if (httpd_query_key_value(buf, "cmd", cmd_val, sizeof(cmd_val)) == ESP_OK) {
        char c = cmd_val[0];
        // Relay command over UART to Arduino
        Serial.write(c);
      }
    }
    free(buf);
  }

  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  return httpd_resp_send(req, "OK", 2);
}

// ==========================================
// INTERACTIVE WEB DASHBOARD (PORT 80)
// ==========================================
static esp_err_t index_handler(httpd_req_t *req) {
  const char html_page[] = 
    "<!DOCTYPE html><html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
    "<title>Aqua-Sentry Teleoperation Deck</title>"
    "<style>"
    "body{font-family:Arial,sans-serif;background:#0d1117;color:#c9d1d9;margin:0;padding:15px;display:flex;flex-direction:column;align-items:center;}"
    "h2{color:#58a6ff;margin:0 0 10px 0;}"
    ".stream-box{position:relative;border:2px solid #30363d;border-radius:8px;overflow:hidden;box-shadow:0 6px 16px rgba(0,0,0,0.7);max-width:640px;width:100%;background:#000;}"
    "img{width:100%;height:auto;display:block;}"
    ".controls{display:grid;grid-template-columns:repeat(3,75px);grid-gap:10px;margin-top:15px;justify-content:center;}"
    "button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:15px;font-size:16px;font-weight:bold;cursor:pointer;touch-action:manipulation;}"
    "button:active{background:#388bfd;color:#fff;}"
    ".btn-stop{background:#da3633;color:#fff;border-color:#f85149;}"
    ".btn-stop:active{background:#b62324;}"
    ".btn-mode{background:#238636;color:#fff;border-color:#2ea043;}"
    ".aux-panel{display:flex;gap:10px;margin-top:15px;}"
    ".status{font-size:13px;color:#7ee787;margin-top:10px;}"
    "</style>"
    "<script>"
    "function sendCmd(c){fetch('/control?cmd='+c);}"
    "document.addEventListener('keydown',function(e){"
    "  if(e.key==='w'||e.key==='ArrowUp')sendCmd('F');"
    "  else if(e.key==='s'||e.key==='ArrowDown')sendCmd('B');"
    "  else if(e.key==='a'||e.key==='ArrowLeft')sendCmd('L');"
    "  else if(e.key==='d'||e.key==='ArrowRight')sendCmd('R');"
    "  else if(e.key===' ')sendCmd('S');"
    "});"
    "</script></head><body>"
    "<h2>Aqua-Sentry Teleoperation</h2>"
    "<div class='stream-box'><img src=':81/stream' alt='Live Stream'></div>"
    "<div class='status'>&bull; AP: AquaSentry-Vision (192.168.4.1) | Keyboard: W/A/S/D, Space</div>"
    "<div class='controls'>"
    "  <div></div><button onclick=\"sendCmd('F')\">&#9650;<br>FWD</button><div></div>"
    "  <button onclick=\"sendCmd('L')\">&#9664;<br>LEFT</button>"
    "  <button class='btn-stop' onclick=\"sendCmd('S')\">BRAKE</button>"
    "  <button onclick=\"sendCmd('R')\">RIGHT<br>&#9654;</button>"
    "  <div></div><button onclick=\"sendCmd('B')\">REV<br>&#9660;</button><div></div>"
    "</div>"
    "<div class='aux-panel'>"
    "  <button class='btn-mode' onclick=\"sendCmd('M')\">Manual Mode</button>"
    "  <button class='btn-mode' onclick=\"sendCmd('A')\">Auto Mode</button>"
    "  <button onclick=\"sendCmd('C')\">Toggle Collector</button>"
    "  <button class='btn-stop' onclick=\"sendCmd('X')\">EMERGENCY KILL</button>"
    "</div>"
    "</body></html>";

  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, html_page, strlen(html_page));
}

// ==========================================
// SERVER INITIALIZATION
// ==========================================
void startCameraServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;

  httpd_config_t stream_config = HTTPD_DEFAULT_CONFIG();
  stream_config.server_port = 81;
  stream_config.ctrl_port = 32769;

  httpd_uri_t index_uri = { .uri = "/", .method = HTTP_GET, .handler = index_handler, .user_ctx = NULL };
  httpd_uri_t ctrl_uri  = { .uri = "/control", .method = HTTP_GET, .handler = control_handler, .user_ctx = NULL };
  httpd_uri_t stream_uri= { .uri = "/stream", .method = HTTP_GET, .handler = stream_handler, .user_ctx = NULL };

  if (httpd_start(&index_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(index_httpd, &index_uri);
    httpd_register_uri_handler(index_httpd, &ctrl_uri);
  }

  if (httpd_start(&stream_httpd, &stream_config) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &stream_uri);
  }
}

// ==========================================
// SETUP
// ==========================================
void setup() {
  // UART baud rate matching Arduino Uno
  Serial.begin(115200);

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()) {
    config.frame_size   = FRAMESIZE_VGA;
    config.jpeg_quality = 12;
    config.fb_count     = 2;
  } else {
    config.frame_size   = FRAMESIZE_SVGA;
    config.jpeg_quality = 14;
    config.fb_count     = 1;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[ERROR] Camera init failed: 0x%x\n", err);
    return;
  }

  sensor_t * s = esp_camera_sensor_get();
  s->set_vflip(s, 1);
  s->set_hmirror(s, 0);

  WiFi.softAP(AP_SSID, AP_PASS);
  startCameraServer();
}

void loop() {
  delay(10000);
}
