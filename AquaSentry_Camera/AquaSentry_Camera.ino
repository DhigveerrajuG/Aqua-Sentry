/**
 * ============================================================================
 * Project: Aqua-Sentry Vision Subsystem (ESP32-CAM)
 * Target Hardware: AI-Thinker ESP32-CAM with OV2640 Sensor
 * 
 * Functionality:
 *   - Creates a dedicated standalone Wi-Fi Access Point ("AquaSentry-Vision").
 *   - No external router or internet needed for open-water testing.
 *   - Hosts an ultra-low-latency MJPEG video stream on port 80 / 81.
 *   - Access via laptop web browser at: http://192.168.4.1
 * ============================================================================
 */

#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"

// ==========================================
// WI-FI ACCESS POINT CREDENTIALS
// ==========================================
const char* AP_SSID = "AquaSentry-Vision";
const char* AP_PASS = "aquasentry123";  // At least 8 characters, or set to NULL for open network

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
// MJPEG STREAM HANDLER
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
      Serial.println(F("[CAMERA] Frame capture failed"));
      res = ESP_FAIL;
      break;
    }

    if (fb->format != PIXFORMAT_JPEG) {
      bool jpeg_converted = frame2jpg(fb, 80, &_jpg_buf, &_jpg_buf_len);
      esp_camera_fb_return(fb);
      fb = NULL;
      if (!jpeg_converted) {
        Serial.println(F("[CAMERA] JPEG conversion error"));
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

    if (res != ESP_OK) {
      break;
    }
  }
  return res;
}

// ==========================================
// MAIN WEB PAGE (HTML INTERFACE)
// ==========================================
static esp_err_t index_handler(httpd_req_t *req) {
  const char html_page[] = 
    "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'>"
    "<title>Aqua-Sentry Live Deck Camera</title>"
    "<style>"
    "body{font-family:Arial,sans-serif;background:#0d1117;color:#c9d1d9;margin:0;padding:20px;display:flex;flex-direction:column;align-items:center;}"
    "h1{color:#58a6ff;margin-bottom:8px;font-size:24px;}"
    ".status{margin-bottom:15px;color:#7ee787;font-size:14px;}"
    ".stream-container{position:relative;border:2px solid #30363d;border-radius:10px;overflow:hidden;box-shadow:0 8px 24px rgba(0,0,0,0.6);background:#000;}"
    "img{display:block;max-width:100%;height:auto;}"
    ".crosshair{position:absolute;top:50%;left:50%;width:40px;height:40px;border:2px solid rgba(88,166,255,0.7);transform:translate(-50%,-50%);border-radius:50%;pointer-events:none;}"
    ".footer{margin-top:20px;font-size:12px;color:#8b949e;}"
    "</style></head><body>"
    "<h1>Aqua-Sentry Live Stream</h1>"
    "<div class='status'>&bull; Catamaran Deck Cam Connected (Local AP: 192.168.4.1)</div>"
    "<div class='stream-container'>"
    "  <img src='/stream' alt='Live Video Stream'>"
    "  <div class='crosshair'></div>"
    "</div>"
    "<div class='footer'>Central Channel Targeting Reticle Active</div>"
    "</body></html>";

  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, html_page, strlen(html_page));
}

// ==========================================
// HTTP SERVER INITIALIZATION
// ==========================================
void startCameraServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;

  // Stream Server Configuration
  httpd_config_t stream_config = HTTPD_DEFAULT_CONFIG();
  stream_config.server_port = 81;
  stream_config.ctrl_port = 32769;

  httpd_uri_t index_uri = {
    .uri       = "/",
    .method    = HTTP_GET,
    .handler   = index_handler,
    .user_ctx  = NULL
  };

  httpd_uri_t stream_uri = {
    .uri       = "/stream",
    .method    = HTTP_GET,
    .handler   = stream_handler,
    .user_ctx  = NULL
  };

  if (httpd_start(&index_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(index_httpd, &index_uri);
    httpd_register_uri_handler(index_httpd, &stream_uri);
  }

  if (httpd_start(&stream_httpd, &stream_config) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &stream_uri);
  }
}

// ==========================================
// SETUP
// ==========================================
void setup() {
  Serial.begin(115200);
  Serial.println(F("\n[INIT] Aqua-Sentry ESP32-CAM Booting..."));

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

  // Frame size & quality tuning for high FPS and low wireless latency
  if (psramFound()) {
    config.frame_size   = FRAMESIZE_VGA;   // 640x480
    config.jpeg_quality = 12;              // 10-63 (lower = better quality)
    config.fb_count     = 2;
  } else {
    config.frame_size   = FRAMESIZE_SVGA;  // Fallback for non-PSRAM
    config.jpeg_quality = 14;
    config.fb_count     = 1;
  }

  // Camera Initialization
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[ERROR] Camera init failed with error 0x%x\n", err);
    return;
  }

  // Optional sensor orientation tweaks (flip if mounted upside-down)
  sensor_t * s = esp_camera_sensor_get();
  s->set_vflip(s, 1);       // 1 = flip vertical
  s->set_hmirror(s, 0);     // 0 = normal horizontal

  // Start Standalone Wi-Fi Access Point
  Serial.print(F("[WIFI] Creating AP: "));
  Serial.println(AP_SSID);
  WiFi.softAP(AP_SSID, AP_PASS);

  IPAddress IP = WiFi.softAPIP();
  Serial.print(F("[WIFI] AP Started! Connect laptop to SSID 'AquaSentry-Vision'."));
  Serial.print(F("\n[STREAM] Access Camera Stream at: http://"));
  Serial.println(IP);

  // Start HTTP Video Stream Servers
  startCameraServer();
  Serial.println(F("[SYSTEM] Video Server Online. Ready for monitoring!"));
}

void loop() {
  delay(10000); // Main loop idle; camera streaming runs asynchronously in FreeRTOS tasks
}
