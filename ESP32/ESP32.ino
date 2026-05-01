#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <ArduinoJson.h>
#include <math.h>

// -----------------------------------------------------------------------------
// TFT
// -----------------------------------------------------------------------------
#define TFT_BL   4
#define TFT_CS   5
#define TFT_DC   6
#define TFT_RST  7
#define TFT_MOSI 15
#define TFT_SCLK 16

SPIClass hspi(HSPI);
Adafruit_ILI9341 tft = Adafruit_ILI9341(&hspi, TFT_DC, TFT_CS, TFT_RST);
GFXcanvas16 canvas(320, 240);

// -----------------------------------------------------------------------------
// UART DESDE RASPBERRY
// Raspberry TX GPIO14 -> ESP32 RX
// Raspberry RX GPIO15 <- ESP32 TX opcional
// GND Raspberry -> GND ESP32
// -----------------------------------------------------------------------------
#define SHANY_RX 18
#define SHANY_TX 17

HardwareSerial ShanyUart(1);
String uartLine = "";

// -----------------------------------------------------------------------------
// COLORES
// -----------------------------------------------------------------------------
#define BLACK      0x0000
#define MINT_CORE  0xC7FD
#define MINT_EDGE  0xC7DC
#define MINT_G1    0xAF5A
#define MINT_G2    0x96D8
#define MINT_G3    0x7E56
#define MINT_G4    0x5DD3
#define MINT_G5    0x3550

// -----------------------------------------------------------------------------
// PANTALLA
// -----------------------------------------------------------------------------
const int SCREEN_W = 320;
const int SCREEN_H = 240;
const int CX = 160;
const int FACE_GLOBAL_Y = 14;

// -----------------------------------------------------------------------------
// EXPRESIONES
// -----------------------------------------------------------------------------
enum FaceExpression {
  FACE_DEFAULT,
  FACE_HAPPY,
  FACE_SURPRISED,
  FACE_LISTENING,
  FACE_EMPATHY,
  FACE_DOUBT,
  FACE_SLEEPING,
  FACE_SLEEPY
};

enum SwapState {
  SWAP_IDLE,
  SWAP_CLOSING,
  SWAP_HOLD_CLOSED,
  SWAP_OPENING
};

enum UiMode {
  UI_IDLE,
  UI_LISTENING
};

enum IdleCycleState {
  IDLE_FACE_DEFAULT,
  IDLE_FACE_SLEEPING,
  IDLE_FACE_SLEEPY
};

FaceExpression currentFace = FACE_DEFAULT;
FaceExpression targetFace  = FACE_DEFAULT;
FaceExpression activeConversationFace = FACE_DEFAULT;

SwapState swapState = SWAP_IDLE;
UiMode uiMode = UI_IDLE;
IdleCycleState idleCycle = IDLE_FACE_DEFAULT;

// -----------------------------------------------------------------------------
// TIEMPOS
// -----------------------------------------------------------------------------
unsigned long faceEnteredAt = 0;

unsigned long swapStateStart = 0;
const unsigned long SWAP_CLOSE_MS = 140;
const unsigned long SWAP_HOLD_MS  = 70;
const unsigned long SWAP_OPEN_MS  = 160;

bool blinking = false;
unsigned long blinkStart = 0;
unsigned long nextBlinkTime = 0;
const unsigned long BLINK_MS = 190;

// Ciclo cuando NO hay llamada activa:
// despierto 2 min -> durmiendo 1 min -> somnoliento 20 s -> despierto
unsigned long idleCycleStart = 0;
const unsigned long IDLE_DEFAULT_MS  = 120000UL;
const unsigned long IDLE_SLEEPING_MS = 60000UL;
const unsigned long IDLE_SLEEPY_MS   = 20000UL;

unsigned long emotionHoldUntil = 0;

// -----------------------------------------------------------------------------
// ESTADO DE SESION Y HABLA
// -----------------------------------------------------------------------------
bool sessionActive = false;
bool isSpeaking = false;
bool blinkAllowed = true;

float mouthTarget = 0.0f;
float mouthDisplay = 0.0f;
float emotionIntensity = 0.6f;

// Para cerrar la boca entre paquetes speech.
// Raspberry suele mandar speech cada ~80 ms. Si pasa más de esto, cerramos.
unsigned long lastMouthPacketMs = 0;
const unsigned long MOUTH_PACKET_TIMEOUT_MS = 120;

// -----------------------------------------------------------------------------
// OJOS / MIRADA
// -----------------------------------------------------------------------------
float eyeOpenFactor = 1.0f;

float gazeX = 0.0f;
float gazeY = 0.0f;
float gazeTargetX = 0.0f;
float gazeTargetY = 0.0f;

unsigned long lastGazeChange = 0;
unsigned long gazeHoldTime = 1800;

// -----------------------------------------------------------------------------
// LAYOUT GENERAL
// -----------------------------------------------------------------------------
const int EYE_OFFSET_X = 82;
const int EYE_Y = 88;
const int EYE_RX = 25;
const int EYE_RY = 54;

// -----------------------------------------------------------------------------
// BOCA PREDETERMINADA
// -----------------------------------------------------------------------------
const int DEFAULT_MOUTH_X = 160;
const int DEFAULT_MOUTH_Y = 177;
const int DEFAULT_MOUTH_W = 60;
const int DEFAULT_MOUTH_CURVE = 12;
const int DEFAULT_MOUTH_THICKNESS = 14;

// -----------------------------------------------------------------------------
// BOCA FELIZ
// -----------------------------------------------------------------------------
const int HAPPY_MOUTH_X = 160;
const int HAPPY_MOUTH_TOP_Y = 166;
const int HAPPY_MOUTH_W = 72;
const int HAPPY_MOUTH_H = 38;
const int HAPPY_MOUTH_CORNER = 6;
const int HAPPY_MOUTH_FLAT_H = 5;

// -----------------------------------------------------------------------------
// BOCA SORPRENDIDA
// -----------------------------------------------------------------------------
const int SURPRISED_MOUTH_X = 160;
const int SURPRISED_MOUTH_Y = 171;
const int SURPRISED_MOUTH_RX = 17;
const int SURPRISED_MOUTH_RY = 28;

// -----------------------------------------------------------------------------
// ESCUCHANDO
// -----------------------------------------------------------------------------
const int LISTENING_MOUTH_X = 160;
const int LISTENING_MOUTH_Y = 182;
const int LISTENING_MOUTH_W = 54;
const int LISTENING_MOUTH_CURVE = 8;
const int LISTENING_MOUTH_THICKNESS = 12;

const int LISTENING_EYE_EXTRA_Y = 14;
const int LISTENING_BROW_THICKNESS = 7;
const int LISTENING_BROW_Y_OFFSET = -78;

// -----------------------------------------------------------------------------
// EMPATIA
// -----------------------------------------------------------------------------
const int EMPATHY_MOUTH_X = 160;
const int EMPATHY_MOUTH_Y = 180;
const int EMPATHY_MOUTH_W = 58;
const int EMPATHY_MOUTH_CURVE = 10;
const int EMPATHY_MOUTH_THICKNESS = 13;

const int EMPATHY_BROW_THICKNESS = 8;
const int EMPATHY_BROW_Y_OFFSET = -64;

const int EMPATHY_EYE_RX = 21;
const int EMPATHY_EYE_RY = 44;
const int EMPATHY_EYE_EXTRA_Y = 8;

// -----------------------------------------------------------------------------
// DUDA
// -----------------------------------------------------------------------------
const int DOUBT_MOUTH_X = 160;
const int DOUBT_MOUTH_Y = 181;
const int DOUBT_MOUTH_W = 48;
const int DOUBT_MOUTH_THICKNESS = 12;

const int DOUBT_BROW_THICKNESS = 9;
const int DOUBT_BROW_Y_OFFSET = -58;

const int DOUBT_EYE_RX = 21;
const int DOUBT_EYE_RY = 44;
const int DOUBT_EYE_EXTRA_Y = 8;

// -----------------------------------------------------------------------------
// DURMIENDO
// -----------------------------------------------------------------------------
const int SLEEP_EYE_Y = 90;
const int SLEEP_EYE_HALF_W = 28;
const int SLEEP_EYE_ARCH_H = 10;
const int SLEEP_EYE_THICKNESS = 14;

const int SLEEP_MOUTH_X = 156;
const int SLEEP_MOUTH_Y = 182;
const int SLEEP_MOUTH_W = 34;
const int SLEEP_MOUTH_CURVE = 7;
const int SLEEP_MOUTH_THICKNESS = 10;

const int SLEEP_Z1_X = 184;
const int SLEEP_Z1_Y = 164;
const int SLEEP_Z1_W = 11;
const int SLEEP_Z1_H = 14;
const int SLEEP_Z1_T = 4;

const int SLEEP_Z2_X = 206;
const int SLEEP_Z2_Y = 145;
const int SLEEP_Z2_W = 15;
const int SLEEP_Z2_H = 18;
const int SLEEP_Z2_T = 5;

const int SLEEP_Z3_X = 233;
const int SLEEP_Z3_Y = 120;
const int SLEEP_Z3_W = 20;
const int SLEEP_Z3_H = 24;
const int SLEEP_Z3_T = 6;

const unsigned long SLEEP_Z_CYCLE_MS = 2800;
const unsigned long SLEEP_Z_DELAY_MS = 420;
const unsigned long SLEEP_Z_LIFE_MS  = 950;
const int SLEEP_Z_FLOAT_UP           = 22;
const int SLEEP_Z_FLOAT_RIGHT        = 8;

// -----------------------------------------------------------------------------
// SOMNOLIENTA
// -----------------------------------------------------------------------------
const unsigned long SLEEPY_WAKE_MS = 20000UL;

const int SLEEPY_EYE_Y = 95;
const int SLEEPY_EYE_RX = 21;

const int SLEEPY_LEFT_EYE_RY_MIN  = 4;
const int SLEEPY_LEFT_EYE_RY_MAX  = 23;
const int SLEEPY_RIGHT_EYE_RY_MIN = 3;
const int SLEEPY_RIGHT_EYE_RY_MAX = 20;

const int SLEEPY_MOUTH_X = 160;
const int SLEEPY_MOUTH_Y = 183;
const int SLEEPY_MOUTH_W_MIN = 26;
const int SLEEPY_MOUTH_W_MAX = 46;
const int SLEEPY_MOUTH_CURVE_MIN = 3;
const int SLEEPY_MOUTH_CURVE_MAX = 9;
const int SLEEPY_MOUTH_THICKNESS = 10;

// -----------------------------------------------------------------------------
// HELPERS
// -----------------------------------------------------------------------------
float clamp01(float v) {
  if (v < 0.0f) return 0.0f;
  if (v > 1.0f) return 1.0f;
  return v;
}

float easeInOut(float t) {
  t = clamp01(t);
  return t * t * (3.0f - 2.0f * t);
}

float sleepyProgressRaw() {
  unsigned long elapsed = millis() - faceEnteredAt;
  return clamp01((float)elapsed / (float)SLEEPY_WAKE_MS);
}

float smoothPulse(float p, float center, float width) {
  float d = fabsf(p - center) / width;

  if (d >= 1.0f) {
    return 0.0f;
  }

  return 1.0f - easeInOut(d);
}

void clearCanvas() {
  canvas.fillScreen(BLACK);
}

void scheduleNextBlink() {
  nextBlinkTime = millis() + random(2300, 5200);
}

// -----------------------------------------------------------------------------
// DIBUJO BASE
// -----------------------------------------------------------------------------
void fillEllipseCanvas(int cx, int cy, int rx, int ry, uint16_t color) {
  if (rx < 1) rx = 1;
  if (ry < 1) ry = 1;

  for (int y = -ry; y <= ry; y = y + 1) {
    float yy = (float)(y * y) / (float)(ry * ry);
    float xx = 1.0f - yy;

    if (xx < 0.0f) {
      xx = 0.0f;
    }

    int halfWidth = (int)(rx * sqrtf(xx));
    canvas.drawFastHLine(cx - halfWidth, cy + y, (2 * halfWidth) + 1, color);
  }
}

void drawSmoothGlowEllipse(int cx, int cy, int rx, int ry) {
  fillEllipseCanvas(cx, cy, rx + 9, ry + 9, MINT_G5);
  fillEllipseCanvas(cx, cy, rx + 7, ry + 7, MINT_G4);
  fillEllipseCanvas(cx, cy, rx + 5, ry + 5, MINT_G3);
  fillEllipseCanvas(cx, cy, rx + 3, ry + 3, MINT_G2);
  fillEllipseCanvas(cx, cy, rx + 2, ry + 2, MINT_G1);
  fillEllipseCanvas(cx, cy, rx + 1, ry + 1, MINT_EDGE);
  fillEllipseCanvas(cx, cy, rx,     ry,     MINT_CORE);
}

void drawGlowEye(int cx, int cy, int rx, int ry) {
  if (ry < 3) ry = 3;
  drawSmoothGlowEllipse(cx, cy, rx, ry);
}

void drawGlowOvalMouth(int cx, int cy, int rx, int ry) {
  drawSmoothGlowEllipse(cx, cy, rx, ry);
}

void drawThickQuadraticBezier(
  int x0, int y0,
  int x1, int y1,
  int x2, int y2,
  int thickness,
  uint16_t color
) {
  const int steps = 56;

  for (int i = 0; i <= steps; i = i + 1) {
    float t = (float)i / (float)steps;
    float u = 1.0f - t;

    float x = (u * u * x0) + (2.0f * u * t * x1) + (t * t * x2);
    float y = (u * u * y0) + (2.0f * u * t * y1) + (t * t * y2);

    canvas.fillCircle((int)x, (int)y, thickness / 2, color);
  }
}

void drawThickLineSegment(
  int x0, int y0,
  int x1, int y1,
  int thickness,
  uint16_t color
) {
  const int steps = 36;

  for (int i = 0; i <= steps; i = i + 1) {
    float t = (float)i / (float)steps;

    float x = x0 + ((x1 - x0) * t);
    float y = y0 + ((y1 - y0) * t);

    canvas.fillCircle((int)x, (int)y, thickness / 2, color);
  }
}

void drawSoftGlowLine(
  int x0, int y0,
  int x1, int y1,
  int thickness
) {
  drawThickLineSegment(x0, y0, x1, y1, thickness + 4, MINT_G4);
  drawThickLineSegment(x0, y0, x1, y1, thickness + 3, MINT_G3);
  drawThickLineSegment(x0, y0, x1, y1, thickness + 2, MINT_G2);
  drawThickLineSegment(x0, y0, x1, y1, thickness + 1, MINT_G1);
  drawThickLineSegment(x0, y0, x1, y1, thickness,     MINT_CORE);
}

void drawGlowBezier(
  int x0, int y0,
  int x1, int y1,
  int x2, int y2,
  int thickness
) {
  drawThickQuadraticBezier(x0, y0, x1, y1, x2, y2, thickness + 8, MINT_G5);
  drawThickQuadraticBezier(x0, y0, x1, y1, x2, y2, thickness + 6, MINT_G4);
  drawThickQuadraticBezier(x0, y0, x1, y1, x2, y2, thickness + 4, MINT_G3);
  drawThickQuadraticBezier(x0, y0, x1, y1, x2, y2, thickness + 2, MINT_G2);
  drawThickQuadraticBezier(x0, y0, x1, y1, x2, y2, thickness + 1, MINT_G1);
  drawThickQuadraticBezier(x0, y0, x1, y1, x2, y2, thickness,     MINT_CORE);
}

void drawSoftGlowBezier(
  int x0, int y0,
  int x1, int y1,
  int x2, int y2,
  int thickness
) {
  drawThickQuadraticBezier(x0, y0, x1, y1, x2, y2, thickness + 4, MINT_G4);
  drawThickQuadraticBezier(x0, y0, x1, y1, x2, y2, thickness + 3, MINT_G3);
  drawThickQuadraticBezier(x0, y0, x1, y1, x2, y2, thickness + 2, MINT_G2);
  drawThickQuadraticBezier(x0, y0, x1, y1, x2, y2, thickness + 1, MINT_G1);
  drawThickQuadraticBezier(x0, y0, x1, y1, x2, y2, thickness,     MINT_CORE);
}

// -----------------------------------------------------------------------------
// BOCAS
// -----------------------------------------------------------------------------
void drawGlowDefaultMouth(int cx, int cy, int width, int curveHeight, int thickness) {
  int x0 = cx - (width / 2);
  int y0 = cy;

  int x1 = cx;
  int y1 = cy + curveHeight;

  int x2 = cx + (width / 2);
  int y2 = cy;

  drawGlowBezier(x0, y0, x1, y1, x2, y2, thickness);
}

void drawGlowDoubtMouth(int cx, int cy, int width, int thickness) {
  int x0 = cx - (width / 2);
  int y0 = cy + 3;

  int x1 = cx;
  int y1 = cy - 7;

  int x2 = cx + (width / 2);
  int y2 = cy - 3;

  drawSoftGlowBezier(x0, y0, x1, y1, x2, y2, thickness);
}

void fillHappyBowlShape(
  int cx,
  int topY,
  int w,
  int h,
  int cornerR,
  int flatH,
  uint16_t color
) {
  if (w < 4) w = 4;
  if (h < 4) h = 4;
  if (cornerR < 0) cornerR = 0;
  if (flatH < 0) flatH = 0;
  if (flatH > h - 2) flatH = h - 2;

  float rx = (float)w / 2.0f;
  int curveH = h - flatH;

  for (int y = 0; y <= h; y = y + 1) {
    float halfWidth;

    if (y <= flatH) {
      halfWidth = rx;
    } else {
      float t = (float)(y - flatH) / (float)curveH;
      t = clamp01(t);
      halfWidth = rx * sqrtf(1.0f - (t * t));
    }

    if (cornerR > 0 && y < cornerR) {
      float dy = (float)(cornerR - y);
      float inside = (float)(cornerR * cornerR) - (dy * dy);

      if (inside < 0.0f) {
        inside = 0.0f;
      }

      float inset = (float)cornerR - sqrtf(inside);
      halfWidth = halfWidth - inset;
    }

    if (halfWidth < 1.0f) {
      halfWidth = 1.0f;
    }

    int hw = (int)halfWidth;
    canvas.drawFastHLine(cx - hw, topY + y, (2 * hw) + 1, color);
  }
}

void drawGlowHappyMouth(int cx, int topY, int w, int h, int cornerR, int flatH) {
  fillHappyBowlShape(cx, topY - 4, w + 8, h + 8, cornerR + 3, flatH + 2, MINT_G4);
  fillHappyBowlShape(cx, topY - 3, w + 6, h + 6, cornerR + 2, flatH + 1, MINT_G3);
  fillHappyBowlShape(cx, topY - 2, w + 4, h + 4, cornerR + 1, flatH + 1, MINT_G2);
  fillHappyBowlShape(cx, topY - 1, w + 2, h + 2, cornerR,     flatH,     MINT_G1);
  fillHappyBowlShape(cx, topY,     w,     h,     cornerR,     flatH,     MINT_CORE);
}

// -----------------------------------------------------------------------------
// BOCA HABLANDO SEGUN EMOCION
// -----------------------------------------------------------------------------
void drawTalkingNeutralMouth(float m) {
  int w = 42 + (int)(m * 12.0f);
  int curve = 5 + (int)(m * 19.0f);
  int thick = 9 + (int)(m * 13.0f);
  int y = DEFAULT_MOUTH_Y + FACE_GLOBAL_Y + (int)(m * 4.0f);

  drawGlowDefaultMouth(DEFAULT_MOUTH_X, y, w, curve, thick);
}

void drawTalkingHappyMouth(float m) {
  int w = HAPPY_MOUTH_W + (int)(m * 8.0f);
  int h = 18 + (int)(m * 32.0f);
  int topY = HAPPY_MOUTH_TOP_Y + FACE_GLOBAL_Y + 4 - (int)(m * 2.0f);

  drawGlowHappyMouth(
    HAPPY_MOUTH_X,
    topY,
    w,
    h,
    HAPPY_MOUTH_CORNER,
    HAPPY_MOUTH_FLAT_H
  );
}

void drawTalkingSurprisedMouth(float m) {
  int rx = 12 + (int)(m * 9.0f);
  int ry = 10 + (int)(m * 23.0f);

  drawGlowOvalMouth(
    SURPRISED_MOUTH_X,
    SURPRISED_MOUTH_Y + FACE_GLOBAL_Y,
    rx,
    ry
  );
}

void drawTalkingEmpathyMouth(float m) {
  int w = EMPATHY_MOUTH_W - 8 + (int)(m * 8.0f);
  int curve = 5 + (int)(m * 15.0f);
  int thick = 8 + (int)(m * 10.0f);
  int y = EMPATHY_MOUTH_Y + FACE_GLOBAL_Y + (int)(m * 4.0f);

  drawGlowDefaultMouth(EMPATHY_MOUTH_X, y, w, curve, thick);
}

void drawTalkingDoubtMouth(float m) {
  int w = DOUBT_MOUTH_W + (int)(m * 10.0f);
  int thick = 8 + (int)(m * 11.0f);
  int cy = DOUBT_MOUTH_Y + FACE_GLOBAL_Y + (int)(m * 4.0f);

  int x0 = DOUBT_MOUTH_X - (w / 2);
  int y0 = cy + 3 + (int)(m * 2.0f);

  int x1 = DOUBT_MOUTH_X;
  int y1 = cy - 6 + (int)(m * 10.0f);

  int x2 = DOUBT_MOUTH_X + (w / 2);
  int y2 = cy - 2 + (int)(m * 3.0f);

  drawSoftGlowBezier(x0, y0, x1, y1, x2, y2, thick);
}

void drawTalkingMouthForFace(FaceExpression face) {
  float m = clamp01(mouthDisplay);

  if (m < 0.035f) {
    if (face == FACE_HAPPY) {
      drawTalkingHappyMouth(0.05f);
    }
    else if (face == FACE_SURPRISED) {
      drawTalkingSurprisedMouth(0.05f);
    }
    else if (face == FACE_EMPATHY) {
      drawTalkingEmpathyMouth(0.05f);
    }
    else if (face == FACE_DOUBT) {
      drawTalkingDoubtMouth(0.05f);
    }
    else {
      drawTalkingNeutralMouth(0.05f);
    }
    return;
  }

  if (face == FACE_HAPPY) {
    drawTalkingHappyMouth(m);
  }
  else if (face == FACE_SURPRISED) {
    drawTalkingSurprisedMouth(m);
  }
  else if (face == FACE_EMPATHY) {
    drawTalkingEmpathyMouth(m);
  }
  else if (face == FACE_DOUBT) {
    drawTalkingDoubtMouth(m);
  }
  else {
    drawTalkingNeutralMouth(m);
  }
}

// -----------------------------------------------------------------------------
// Z
// -----------------------------------------------------------------------------
void drawGlowZ(int x, int y, int w, int h, int thickness) {
  drawSoftGlowLine(x,     y,     x + w, y,     thickness);
  drawSoftGlowLine(x + w, y,     x,     y + h, thickness);
  drawSoftGlowLine(x,     y + h, x + w, y + h, thickness);
}

void drawAnimatedOneSleepZ(
  int baseX,
  int baseY,
  int baseW,
  int baseH,
  int baseT,
  unsigned long startDelay
) {
  unsigned long cyclePos = millis() % SLEEP_Z_CYCLE_MS;

  if (cyclePos < startDelay) {
    return;
  }

  unsigned long age = cyclePos - startDelay;

  if (age > SLEEP_Z_LIFE_MS) {
    return;
  }

  float p = (float)age / (float)SLEEP_Z_LIFE_MS;
  p = clamp01(p);

  int x = baseX + (int)(SLEEP_Z_FLOAT_RIGHT * p);
  int y = baseY - (int)(SLEEP_Z_FLOAT_UP * p);

  float scale = 0.90f + (0.35f * p);

  int w = (int)(baseW * scale);
  int h = (int)(baseH * scale);
  int t = (int)(baseT * (0.95f + (0.20f * p)));

  if (w < 6) w = 6;
  if (h < 8) h = 8;
  if (t < 3) t = 3;

  drawGlowZ(x, y, w, h, t);
}

void drawAnimatedSleepZs(int offsetX, int offsetY) {
  drawAnimatedOneSleepZ(
    SLEEP_Z1_X + offsetX,
    SLEEP_Z1_Y + FACE_GLOBAL_Y + offsetY,
    SLEEP_Z1_W,
    SLEEP_Z1_H,
    SLEEP_Z1_T,
    0
  );

  drawAnimatedOneSleepZ(
    SLEEP_Z2_X + offsetX,
    SLEEP_Z2_Y + FACE_GLOBAL_Y + offsetY,
    SLEEP_Z2_W,
    SLEEP_Z2_H,
    SLEEP_Z2_T,
    SLEEP_Z_DELAY_MS
  );

  drawAnimatedOneSleepZ(
    SLEEP_Z3_X + offsetX,
    SLEEP_Z3_Y + FACE_GLOBAL_Y + offsetY,
    SLEEP_Z3_W,
    SLEEP_Z3_H,
    SLEEP_Z3_T,
    SLEEP_Z_DELAY_MS * 2
  );
}

// -----------------------------------------------------------------------------
// CEJAS Y OJOS
// -----------------------------------------------------------------------------
void drawSleepingEyes(int offsetX, int offsetY) {
  int leftEyeX  = CX - EYE_OFFSET_X + offsetX;
  int rightEyeX = CX + EYE_OFFSET_X + offsetX;
  int eyeY = SLEEP_EYE_Y + FACE_GLOBAL_Y + offsetY;

  drawSoftGlowBezier(
    leftEyeX - SLEEP_EYE_HALF_W,
    eyeY + 6,
    leftEyeX,
    eyeY - SLEEP_EYE_ARCH_H,
    leftEyeX + SLEEP_EYE_HALF_W,
    eyeY + 6,
    SLEEP_EYE_THICKNESS
  );

  drawSoftGlowBezier(
    rightEyeX - SLEEP_EYE_HALF_W,
    eyeY + 6,
    rightEyeX,
    eyeY - SLEEP_EYE_ARCH_H,
    rightEyeX + SLEEP_EYE_HALF_W,
    eyeY + 6,
    SLEEP_EYE_THICKNESS
  );
}

void drawListeningBrows(int offsetX, int offsetY) {
  int leftEyeX  = CX - EYE_OFFSET_X + offsetX;
  int rightEyeX = CX + EYE_OFFSET_X + offsetX;
  int browY = EYE_Y + FACE_GLOBAL_Y + LISTENING_BROW_Y_OFFSET + offsetY;

  drawSoftGlowBezier(
    leftEyeX - 24,
    browY + 5,
    leftEyeX - 6,
    browY - 8,
    leftEyeX + 18,
    browY - 1,
    LISTENING_BROW_THICKNESS
  );

  drawSoftGlowBezier(
    rightEyeX - 18,
    browY - 1,
    rightEyeX + 6,
    browY - 8,
    rightEyeX + 24,
    browY + 5,
    LISTENING_BROW_THICKNESS
  );
}

void drawEmpathyBrows(int offsetX, int offsetY) {
  int leftEyeX  = CX - EYE_OFFSET_X + offsetX;
  int rightEyeX = CX + EYE_OFFSET_X + offsetX;
  int browY = EYE_Y + FACE_GLOBAL_Y + EMPATHY_BROW_Y_OFFSET + offsetY;

  drawSoftGlowLine(
    leftEyeX - 28,
    browY + 3,
    leftEyeX + 14,
    browY - 13,
    EMPATHY_BROW_THICKNESS
  );

  drawSoftGlowLine(
    rightEyeX - 14,
    browY - 13,
    rightEyeX + 28,
    browY + 3,
    EMPATHY_BROW_THICKNESS
  );
}

void drawDoubtBrows(int offsetX, int offsetY) {
  int leftEyeX  = CX - EYE_OFFSET_X + offsetX;
  int rightEyeX = CX + EYE_OFFSET_X + offsetX;
  int browY = EYE_Y + FACE_GLOBAL_Y + DOUBT_BROW_Y_OFFSET + offsetY;

  drawSoftGlowBezier(
    leftEyeX - 34,
    browY + 12,
    leftEyeX - 8,
    browY - 12,
    leftEyeX + 28,
    browY - 4,
    DOUBT_BROW_THICKNESS
  );

  drawSoftGlowLine(
    rightEyeX - 30,
    browY - 2,
    rightEyeX + 30,
    browY + 20,
    DOUBT_BROW_THICKNESS
  );
}

void drawEyesSized(int offsetX, int offsetY, float openFactor, int rx, int ryBase) {
  int leftEyeX  = CX - EYE_OFFSET_X + offsetX;
  int rightEyeX = CX + EYE_OFFSET_X + offsetX;
  int eyeY = EYE_Y + FACE_GLOBAL_Y + offsetY;

  int eyeRY = (int)(ryBase * openFactor);
  if (eyeRY < 4) eyeRY = 4;

  drawGlowEye(leftEyeX,  eyeY, rx, eyeRY);
  drawGlowEye(rightEyeX, eyeY, rx, eyeRY);
}

void drawEyes(int offsetX, int offsetY, float openFactor) {
  drawEyesSized(offsetX, offsetY, openFactor, EYE_RX, EYE_RY);
}

void drawSleepyWakingEyes(int offsetX, int offsetY) {
  float raw = sleepyProgressRaw();

  float pLeft  = easeInOut(clamp01((raw - 0.05f) / 0.78f));
  float pRight = easeInOut(clamp01((raw - 0.32f) / 0.68f));

  float droop = smoothPulse(raw, 0.56f, 0.16f);

  float sleepyBob = sinf(raw * 3.14159f * 3.0f) * (1.0f - raw);
  int bobY = (int)(sleepyBob * 5.0f);

  int leftEyeX  = CX - EYE_OFFSET_X + offsetX - 3;
  int rightEyeX = CX + EYE_OFFSET_X + offsetX + 3;

  int eyeBaseY = SLEEPY_EYE_Y + FACE_GLOBAL_Y + offsetY + bobY;

  int leftRY =
    SLEEPY_LEFT_EYE_RY_MIN +
    (int)((SLEEPY_LEFT_EYE_RY_MAX - SLEEPY_LEFT_EYE_RY_MIN) * pLeft);

  int rightRY =
    SLEEPY_RIGHT_EYE_RY_MIN +
    (int)((SLEEPY_RIGHT_EYE_RY_MAX - SLEEPY_RIGHT_EYE_RY_MIN) * pRight);

  leftRY  = leftRY  - (int)(droop * 7.0f);
  rightRY = rightRY - (int)(droop * 6.0f);

  if (leftRY < 4) {
    leftRY = 4;
  }

  if (rightRY < 3) {
    rightRY = 3;
  }

  int leftY  = eyeBaseY - (int)(4.0f * pLeft);
  int rightY = eyeBaseY + 3 - (int)(3.0f * pRight);

  drawGlowEye(leftEyeX,  leftY,  SLEEPY_EYE_RX,     leftRY);
  drawGlowEye(rightEyeX, rightY, SLEEPY_EYE_RX - 2, rightRY);
}

// -----------------------------------------------------------------------------
// CARAS COMPLETAS SIN LIP SYNC
// -----------------------------------------------------------------------------
void drawDefaultFace(int offsetX, int offsetY, float openFactor) {
  drawEyes(offsetX, offsetY, openFactor);

  drawGlowDefaultMouth(
    DEFAULT_MOUTH_X,
    DEFAULT_MOUTH_Y + FACE_GLOBAL_Y,
    DEFAULT_MOUTH_W,
    DEFAULT_MOUTH_CURVE,
    DEFAULT_MOUTH_THICKNESS
  );
}

void drawHappyFace(int offsetX, int offsetY, float openFactor) {
  drawEyes(offsetX, offsetY, openFactor);

  drawGlowHappyMouth(
    HAPPY_MOUTH_X,
    HAPPY_MOUTH_TOP_Y + FACE_GLOBAL_Y,
    HAPPY_MOUTH_W,
    HAPPY_MOUTH_H,
    HAPPY_MOUTH_CORNER,
    HAPPY_MOUTH_FLAT_H
  );
}

void drawSurprisedFace(int offsetX, int offsetY, float openFactor) {
  drawEyes(offsetX, offsetY, openFactor);

  drawGlowOvalMouth(
    SURPRISED_MOUTH_X,
    SURPRISED_MOUTH_Y + FACE_GLOBAL_Y,
    SURPRISED_MOUTH_RX,
    SURPRISED_MOUTH_RY
  );
}

void drawListeningFace(int offsetX, int offsetY, float openFactor) {
  drawListeningBrows(offsetX, offsetY);

  drawEyes(offsetX, offsetY + LISTENING_EYE_EXTRA_Y, openFactor);

  drawGlowDefaultMouth(
    LISTENING_MOUTH_X,
    LISTENING_MOUTH_Y + FACE_GLOBAL_Y,
    LISTENING_MOUTH_W,
    LISTENING_MOUTH_CURVE,
    LISTENING_MOUTH_THICKNESS
  );
}

void drawEmpathyFace(int offsetX, int offsetY, float openFactor) {
  drawEyesSized(
    offsetX,
    offsetY + EMPATHY_EYE_EXTRA_Y,
    openFactor,
    EMPATHY_EYE_RX,
    EMPATHY_EYE_RY
  );

  drawEmpathyBrows(offsetX, offsetY);

  drawGlowDefaultMouth(
    EMPATHY_MOUTH_X,
    EMPATHY_MOUTH_Y + FACE_GLOBAL_Y,
    EMPATHY_MOUTH_W,
    EMPATHY_MOUTH_CURVE,
    EMPATHY_MOUTH_THICKNESS
  );
}

void drawDoubtFace(int offsetX, int offsetY, float openFactor) {
  drawEyesSized(
    offsetX,
    offsetY + DOUBT_EYE_EXTRA_Y,
    openFactor,
    DOUBT_EYE_RX,
    DOUBT_EYE_RY
  );

  drawDoubtBrows(offsetX, offsetY);

  drawGlowDoubtMouth(
    DOUBT_MOUTH_X,
    DOUBT_MOUTH_Y + FACE_GLOBAL_Y,
    DOUBT_MOUTH_W,
    DOUBT_MOUTH_THICKNESS
  );
}

void drawSleepingFace(int offsetX, int offsetY, float openFactor) {
  drawSleepingEyes(offsetX, offsetY);

  drawGlowDefaultMouth(
    SLEEP_MOUTH_X,
    SLEEP_MOUTH_Y + FACE_GLOBAL_Y,
    SLEEP_MOUTH_W,
    SLEEP_MOUTH_CURVE,
    SLEEP_MOUTH_THICKNESS
  );

  drawAnimatedSleepZs(offsetX, offsetY);
}

void drawSleepyFace(int offsetX, int offsetY, float openFactor) {
  float raw = sleepyProgressRaw();
  float p = easeInOut(raw);

  float bob = sinf(raw * 3.14159f * 3.0f) * (1.0f - raw);
  int bobY = (int)(bob * 4.0f);

  drawSleepyWakingEyes(offsetX, offsetY);

  int mouthW =
    SLEEPY_MOUTH_W_MIN +
    (int)((SLEEPY_MOUTH_W_MAX - SLEEPY_MOUTH_W_MIN) * p);

  int mouthCurve =
    SLEEPY_MOUTH_CURVE_MIN +
    (int)((SLEEPY_MOUTH_CURVE_MAX - SLEEPY_MOUTH_CURVE_MIN) * p);

  int mouthY = SLEEPY_MOUTH_Y + FACE_GLOBAL_Y + bobY - (int)(2.0f * p);

  int x0 = SLEEPY_MOUTH_X - (mouthW / 2);
  int y0 = mouthY + 3;

  int x1 = SLEEPY_MOUTH_X - 2;
  int y1 = mouthY + mouthCurve + 2 - (int)(2.0f * p);

  int x2 = SLEEPY_MOUTH_X + (mouthW / 2);
  int y2 = mouthY;

  drawSoftGlowBezier(x0, y0, x1, y1, x2, y2, SLEEPY_MOUTH_THICKNESS);
}

// -----------------------------------------------------------------------------
// CARA CON LIP SYNC
// -----------------------------------------------------------------------------
void drawSpeakingFace(int offsetX, int offsetY, float openFactor) {
  FaceExpression faceForEyes = currentFace;

  if (faceForEyes == FACE_SLEEPING || faceForEyes == FACE_SLEEPY || faceForEyes == FACE_LISTENING) {
    faceForEyes = activeConversationFace;
  }

  if (faceForEyes == FACE_DEFAULT) {
    drawEyes(offsetX, offsetY, openFactor);
  }
  else if (faceForEyes == FACE_HAPPY) {
    drawEyes(offsetX, offsetY, openFactor);
  }
  else if (faceForEyes == FACE_SURPRISED) {
    drawEyes(offsetX, offsetY, openFactor);
  }
  else if (faceForEyes == FACE_EMPATHY) {
    drawEyesSized(
      offsetX,
      offsetY + EMPATHY_EYE_EXTRA_Y,
      openFactor,
      EMPATHY_EYE_RX,
      EMPATHY_EYE_RY
    );
    drawEmpathyBrows(offsetX, offsetY);
  }
  else if (faceForEyes == FACE_DOUBT) {
    drawEyesSized(
      offsetX,
      offsetY + DOUBT_EYE_EXTRA_Y,
      openFactor,
      DOUBT_EYE_RX,
      DOUBT_EYE_RY
    );
    drawDoubtBrows(offsetX, offsetY);
  }
  else {
    drawEyes(offsetX, offsetY, openFactor);
  }

  drawTalkingMouthForFace(faceForEyes);
}

// -----------------------------------------------------------------------------
// CAMBIO DE CARA
// -----------------------------------------------------------------------------
void requestFace(FaceExpression newFace) {
  if (newFace == currentFace && swapState == SWAP_IDLE) {
    return;
  }

  if (newFace == targetFace && swapState != SWAP_IDLE) {
    return;
  }

  targetFace = newFace;
  swapState = SWAP_CLOSING;
  swapStateStart = millis();
}

void forceFace(FaceExpression newFace) {
  currentFace = newFace;
  targetFace = newFace;
  swapState = SWAP_IDLE;
  eyeOpenFactor = 1.0f;
  faceEnteredAt = millis();
  scheduleNextBlink();
}

// -----------------------------------------------------------------------------
// MAPEO DE EMOCIONES
// -----------------------------------------------------------------------------
FaceExpression mapEmotionToFace(String emotion) {
  emotion.trim();

  if (emotion == "neutral") {
    return FACE_DEFAULT;
  }

  if (emotion == "alegria_suave") {
    return FACE_HAPPY;
  }

  if (emotion == "sorpresa") {
    return FACE_SURPRISED;
  }

  if (emotion == "empatia") {
    return FACE_EMPATHY;
  }

  if (emotion == "duda") {
    return FACE_DOUBT;
  }

  // Compatibilidad por si ElevenLabs manda nombres antiguos
  if (emotion == "calma") {
    return FACE_DEFAULT;
  }

  if (emotion == "preocupacion_suave") {
    return FACE_EMPATHY;
  }

  if (emotion == "pensando") {
    return FACE_DOUBT;
  }

  if (emotion == "descanso") {
    return FACE_SLEEPING;
  }

  if (emotion == "somnolienta") {
    return FACE_SLEEPY;
  }

  return FACE_DEFAULT;
}

// -----------------------------------------------------------------------------
// ESTADOS PRINCIPALES
// -----------------------------------------------------------------------------
void enterIdleMode() {
  sessionActive = false;
  uiMode = UI_IDLE;
  isSpeaking = false;

  mouthTarget = 0.0f;
  mouthDisplay = 0.0f;

  activeConversationFace = FACE_DEFAULT;
  blinkAllowed = true;

  idleCycle = IDLE_FACE_DEFAULT;
  idleCycleStart = millis();

  forceFace(FACE_DEFAULT);

  Serial.println("UI: idle");
}

void enterListeningMode() {
  sessionActive = true;
  uiMode = UI_LISTENING;
  isSpeaking = false;

  mouthTarget = 0.0f;

  idleCycle = IDLE_FACE_DEFAULT;
  requestFace(FACE_LISTENING);

  Serial.println("UI: listening");
}

void startSpeakingMode() {
  sessionActive = true;
  uiMode = UI_LISTENING;
  isSpeaking = true;

  mouthTarget = 0.0f;
  mouthDisplay = 0.0f;
  lastMouthPacketMs = millis();

  requestFace(activeConversationFace);

  Serial.println("Speech: start");
}

void stopSpeakingMode() {
  isSpeaking = false;
  mouthTarget = 0.0f;

  if (sessionActive) {
    requestFace(FACE_LISTENING);
  }

  Serial.println("Speech: stop");
}

// -----------------------------------------------------------------------------
// JSON
// -----------------------------------------------------------------------------
void handleJson(String payload) {
  payload.trim();

  if (payload.length() == 0) {
    return;
  }

  StaticJsonDocument<384> doc;
  DeserializationError error = deserializeJson(doc, payload);

  if (error) {
    Serial.print("JSON invalido: ");
    Serial.println(payload);
    return;
  }

  String type = doc["type"] | "";

  if (type == "ui_state") {
    String state = doc["state"] | "";

    if (state == "idle") {
      enterIdleMode();
    }
    else if (state == "listening") {
      enterListeningMode();
    }
    else if (state == "sleep") {
      enterIdleMode();
      requestFace(FACE_SLEEPING);
    }
    else if (state == "thinking") {
      sessionActive = true;
      uiMode = UI_LISTENING;
      isSpeaking = false;
      requestFace(FACE_DOUBT);
    }
  }
  else if (type == "emotion") {
    String emotion = doc["emotion"] | "neutral";

    if (doc.containsKey("intensity")) {
      emotionIntensity = clamp01(doc["intensity"].as<float>());
    }

    if (doc.containsKey("blink")) {
      blinkAllowed = doc["blink"].as<bool>();
    }

    int durationMs = 3000;
    if (doc.containsKey("duration_ms")) {
      durationMs = doc["duration_ms"].as<int>();
      if (durationMs < 0) {
        durationMs = 0;
      }
    }

    emotionHoldUntil = millis() + (unsigned long)durationMs;

    FaceExpression mapped = mapEmotionToFace(emotion);
    activeConversationFace = mapped;

    if (sessionActive) {
      requestFace(activeConversationFace);
    }

    Serial.print("Emotion: ");
    Serial.println(emotion);
  }
  else if (type == "speech_state") {
    bool speaking = doc["speaking"] | false;

    if (speaking) {
      startSpeakingMode();
    } else {
      stopSpeakingMode();
    }
  }
  else if (type == "speech") {
    float m = doc["mouth"] | 0.0f;
    mouthTarget = clamp01(m);
    lastMouthPacketMs = millis();
  }
}

void pollShanyUart() {
  while (ShanyUart.available() > 0) {
    char c = (char)ShanyUart.read();

    if (c == '\r') {
      continue;
    }

    if (c == '\n') {
      if (uartLine.length() > 0) {
        handleJson(uartLine);
        uartLine = "";
      }
    } else {
      uartLine += c;

      if (uartLine.length() > 512) {
        uartLine = "";
      }
    }
  }
}

// Permite probar desde el monitor serial pegando JSON manualmente
void pollUsbSerialForTesting() {
  static String usbLine = "";

  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\r') {
      continue;
    }

    if (c == '\n') {
      if (usbLine.length() > 0) {
        handleJson(usbLine);
        usbLine = "";
      }
    } else {
      usbLine += c;

      if (usbLine.length() > 512) {
        usbLine = "";
      }
    }
  }
}

// -----------------------------------------------------------------------------
// ANIMACIONES
// -----------------------------------------------------------------------------
void updateIdleAutoRotation() {
  if (sessionActive) {
    return;
  }

  if (swapState != SWAP_IDLE) {
    return;
  }

  unsigned long now = millis();

  if (idleCycle == IDLE_FACE_DEFAULT) {
    if (now - idleCycleStart >= IDLE_DEFAULT_MS) {
      idleCycle = IDLE_FACE_SLEEPING;
      idleCycleStart = now;
      requestFace(FACE_SLEEPING);
    }
  }
  else if (idleCycle == IDLE_FACE_SLEEPING) {
    if (now - idleCycleStart >= IDLE_SLEEPING_MS) {
      idleCycle = IDLE_FACE_SLEEPY;
      idleCycleStart = now;
      requestFace(FACE_SLEEPY);
    }
  }
  else if (idleCycle == IDLE_FACE_SLEEPY) {
    if (now - idleCycleStart >= IDLE_SLEEPY_MS) {
      idleCycle = IDLE_FACE_DEFAULT;
      idleCycleStart = now;
      requestFace(FACE_DEFAULT);
    }
  }
}

void updateSwapAnimation() {
  unsigned long now = millis();

  if (swapState == SWAP_IDLE) {
    return;
  }

  if (swapState == SWAP_CLOSING) {
    float t = (float)(now - swapStateStart) / (float)SWAP_CLOSE_MS;
    t = easeInOut(clamp01(t));
    eyeOpenFactor = 1.0f - t;

    if (now - swapStateStart >= SWAP_CLOSE_MS) {
      eyeOpenFactor = 0.0f;
      currentFace = targetFace;
      faceEnteredAt = now;
      swapState = SWAP_HOLD_CLOSED;
      swapStateStart = now;
    }
  }
  else if (swapState == SWAP_HOLD_CLOSED) {
    eyeOpenFactor = 0.0f;

    if (now - swapStateStart >= SWAP_HOLD_MS) {
      swapState = SWAP_OPENING;
      swapStateStart = now;
    }
  }
  else if (swapState == SWAP_OPENING) {
    float t = (float)(now - swapStateStart) / (float)SWAP_OPEN_MS;
    t = easeInOut(clamp01(t));
    eyeOpenFactor = t;

    if (now - swapStateStart >= SWAP_OPEN_MS) {
      eyeOpenFactor = 1.0f;
      swapState = SWAP_IDLE;
      scheduleNextBlink();
    }
  }
}

void updateNormalBlink() {
  if (!blinkAllowed) {
    eyeOpenFactor = 1.0f;
    blinking = false;
    return;
  }

  if (swapState != SWAP_IDLE) {
    return;
  }

  if (currentFace == FACE_SLEEPING || currentFace == FACE_SLEEPY) {
    eyeOpenFactor = 1.0f;
    return;
  }

  unsigned long now = millis();

  if (!blinking && now >= nextBlinkTime) {
    blinking = true;
    blinkStart = now;
  }

  if (blinking) {
    unsigned long elapsed = now - blinkStart;

    if (elapsed >= BLINK_MS) {
      blinking = false;
      eyeOpenFactor = 1.0f;
      scheduleNextBlink();
    } else {
      float t = (float)elapsed / (float)BLINK_MS;
      t = clamp01(t);

      if (t < 0.5f) {
        float c = easeInOut(t / 0.5f);
        eyeOpenFactor = 1.0f - c;
      } else {
        float o = easeInOut((t - 0.5f) / 0.5f);
        eyeOpenFactor = o;
      }
    }
  } else {
    eyeOpenFactor = 1.0f;
  }
}

void updateGaze() {
  if (currentFace == FACE_SLEEPING || currentFace == FACE_SLEEPY) {
    gazeX = 0.0f;
    gazeY = 0.0f;
    gazeTargetX = 0.0f;
    gazeTargetY = 0.0f;
    return;
  }

  unsigned long now = millis();

  if (now - lastGazeChange >= gazeHoldTime) {
    lastGazeChange = now;

    if (sessionActive) {
      gazeHoldTime = random(800, 1800);
      gazeTargetX = (float)random(-10, 11);
      gazeTargetY = (float)random(-5, 6);
    } else {
      gazeHoldTime = random(1200, 2600);
      gazeTargetX = (float)random(-8, 9);
      gazeTargetY = (float)random(-4, 5);
    }
  }

  gazeX = gazeX + ((gazeTargetX - gazeX) * 0.08f);
  gazeY = gazeY + ((gazeTargetY - gazeY) * 0.08f);
}

void updateMouth() {
  unsigned long now = millis();

  // Si está hablando pero no llegan nuevos niveles de boca,
  // cerramos localmente para que no se quede congelada abierta.
  if (isSpeaking && (now - lastMouthPacketMs > MOUTH_PACKET_TIMEOUT_MS)) {
    mouthTarget = 0.0f;
  }

  if (isSpeaking) {
    float alpha;

    if (mouthTarget > mouthDisplay) {
      alpha = 0.55f;   // abre rápido
    } else {
      alpha = 0.48f;   // cierra bastante rápido
    }

    mouthDisplay = ((1.0f - alpha) * mouthDisplay) + (alpha * mouthTarget);
  } else {
    mouthDisplay = mouthDisplay * 0.62f;
  }

  if (mouthDisplay < 0.018f) {
    mouthDisplay = 0.0f;
  }
}

// -----------------------------------------------------------------------------
// RENDER
// -----------------------------------------------------------------------------
void renderFace() {
  clearCanvas();

  int lookX = (int)gazeX;
  int lookY = (int)gazeY;

  if (isSpeaking) {
    drawSpeakingFace(lookX, lookY, eyeOpenFactor);
  }
  else if (currentFace == FACE_DEFAULT) {
    drawDefaultFace(lookX, lookY, eyeOpenFactor);
  }
  else if (currentFace == FACE_HAPPY) {
    drawHappyFace(lookX, lookY, eyeOpenFactor);
  }
  else if (currentFace == FACE_SURPRISED) {
    drawSurprisedFace(lookX, lookY, eyeOpenFactor);
  }
  else if (currentFace == FACE_LISTENING) {
    drawListeningFace(lookX, lookY, eyeOpenFactor);
  }
  else if (currentFace == FACE_EMPATHY) {
    drawEmpathyFace(lookX, lookY, eyeOpenFactor);
  }
  else if (currentFace == FACE_DOUBT) {
    drawDoubtFace(lookX, lookY, eyeOpenFactor);
  }
  else if (currentFace == FACE_SLEEPING) {
    drawSleepingFace(lookX, lookY, eyeOpenFactor);
  }
  else if (currentFace == FACE_SLEEPY) {
    drawSleepyFace(lookX, lookY, eyeOpenFactor);
  }

  tft.drawRGBBitmap(0, 0, canvas.getBuffer(), SCREEN_W, SCREEN_H);
}

// -----------------------------------------------------------------------------
// SETUP
// -----------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  ShanyUart.begin(115200, SERIAL_8N1, SHANY_RX, SHANY_TX);

  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, HIGH);

  hspi.begin(TFT_SCLK, -1, TFT_MOSI, TFT_CS);

  tft.begin(40000000);
  tft.setRotation(1);
  tft.fillScreen(BLACK);

  randomSeed(micros());
  scheduleNextBlink();

  currentFace = FACE_DEFAULT;
  targetFace = FACE_DEFAULT;
  activeConversationFace = FACE_DEFAULT;

  faceEnteredAt = millis();
  idleCycleStart = millis();

  sessionActive = false;
  uiMode = UI_IDLE;
  idleCycle = IDLE_FACE_DEFAULT;

  Serial.println("Shany ESP32 face system ready");
  Serial.println("Esperando JSON por UART...");
}

// -----------------------------------------------------------------------------
// LOOP
// -----------------------------------------------------------------------------
void loop() {
  pollShanyUart();

  // Solo para pruebas desde monitor serial USB.
  // Si no lo quieres, puedes comentar esta linea.
  pollUsbSerialForTesting();

  updateIdleAutoRotation();
  updateSwapAnimation();

  if (swapState == SWAP_IDLE) {
    updateNormalBlink();
  }

  updateGaze();
  updateMouth();
  renderFace();

  delay(20);
}