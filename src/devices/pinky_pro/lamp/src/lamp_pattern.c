/*
 * lamp_pattern: show one D-260 robot-state pattern on the Pinky Pro WS2812
 * lamp until told to stop.
 *
 * rosy-boot-display.service (user rosy-display, not root) starts one process
 * per robot state and stops it with SIGTERM when the state changes. The lamp
 * node /dev/ws281x_pwm is granted to that unit alone (udev group rosy-display,
 * DeviceAllow); the colour-setting lamp_control service stays bench-only
 * (D-169). No ROS. Same pinned rpi_ws281x and strip settings as main_node and
 * lamp_selftest (8 LEDs, GPIO19, GBR, rp1_ws281x_pwm pwm_channel=3).
 *
 *   booting  blue, breathing, 2 s period, at most 25 % brightness
 *   ready    green for 3 s, then off and exit
 *   failed   red, 1 Hz blink, until stopped
 *   caution  orange, 0.5 Hz blink, until stopped
 *   test     red, green, blue for 1 s each, then off and exit (D-247 lamp test
 *            handed to the boot display while it owns the lamp)
 *   off      off and exit
 *
 * Exit codes: 0 done or stopped (the lamp is left dark), 2 the library would
 * not start, 3 a frame failed to render, 64 usage. Errors go to stderr.
 */
#define _POSIX_C_SOURCE 200809L

#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#include "ws2811/ws2811.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define LAMP_GPIO 19
#define LAMP_COUNT 8
#define LAMP_DMA 10
#define TICK_MS 50
#define PEAK 255
/* 25 % of full brightness for the breathing blue (D-260 decision 3). */
#define BREATH_MAX (PEAK / 4)
#define DIM 0x40

static volatile sig_atomic_t stop_requested = 0;

static void on_signal(int signum)
{
    (void)signum;
    stop_requested = 1;
}

static ws2811_return_t fill(ws2811_t *lamp, ws2811_led_t color)
{
    for (int i = 0; i < LAMP_COUNT; i++) {
        lamp->channel[0].leds[i] = color;
    }
    return ws2811_render(lamp);
}

static ws2811_led_t rgb(int red, int green, int blue)
{
    /* 0xWWRRGGBB; the library reorders for the GBR strip. */
    return ((ws2811_led_t)red << 16) | ((ws2811_led_t)green << 8) | (ws2811_led_t)blue;
}

/*
 * The colour at elapsed_ms, and whether the pattern is over (ready/test/off).
 * Pure, so the pattern table reads as one function.
 */
static int frame(const char *pattern, long elapsed_ms, ws2811_led_t *color)
{
    if (strcmp(pattern, "booting") == 0) {
        double phase = (double)(elapsed_ms % 2000) / 2000.0;
        int level = (int)lround(BREATH_MAX * (0.5 - 0.5 * cos(2.0 * M_PI * phase)));
        *color = rgb(0, 0, level);
        return 0;
    }
    if (strcmp(pattern, "ready") == 0) {
        *color = rgb(0, DIM, 0);
        return elapsed_ms >= 3000;
    }
    if (strcmp(pattern, "failed") == 0) {
        *color = (elapsed_ms % 1000) < 500 ? rgb(DIM, 0, 0) : 0;
        return 0;
    }
    if (strcmp(pattern, "caution") == 0) {
        *color = (elapsed_ms % 2000) < 1000 ? rgb(DIM, DIM / 3, 0) : 0;
        return 0;
    }
    if (strcmp(pattern, "test") == 0) {
        static const int steps[3][3] = {{0x30, 0, 0}, {0, 0x30, 0}, {0, 0, 0x30}};
        long step = elapsed_ms / 1000;
        if (step >= 3) {
            return 1;
        }
        *color = rgb(steps[step][0], steps[step][1], steps[step][2]);
        return 0;
    }
    /* "off" */
    *color = 0;
    return 1;
}

static int known(const char *pattern)
{
    static const char *names[] = {"booting", "ready", "failed", "caution", "test", "off"};
    for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); i++) {
        if (strcmp(pattern, names[i]) == 0) {
            return 1;
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 2 || !known(argv[1])) {
        fprintf(stderr, "usage: lamp_pattern booting|ready|failed|caution|test|off\n");
        return 64;
    }
    const char *pattern = argv[1];
    ws2811_t lamp = {
        .freq = WS2811_TARGET_FREQ,
        .dmanum = LAMP_DMA,
        .channel = {
            [0] = {
                .gpionum = LAMP_GPIO,
                .invert = 0,
                .count = LAMP_COUNT,
                .strip_type = WS2811_STRIP_GBR,
                .brightness = 255,
            },
        },
    };
    struct sigaction action = {0};
    action.sa_handler = on_signal;
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGINT, &action, NULL);

    ws2811_return_t ret = ws2811_init(&lamp);
    if (ret != WS2811_SUCCESS) {
        fprintf(stderr, "lamp_pattern: ws2811_init: %s\n", ws2811_get_return_t_str(ret));
        return 2;
    }
    int status = 0;
    struct timespec tick = {0, TICK_MS * 1000000L};
    ws2811_led_t shown = 0xFFFFFFFF;
    for (long elapsed = 0; !stop_requested; elapsed += TICK_MS) {
        ws2811_led_t color = 0;
        if (frame(pattern, elapsed, &color)) {
            break;
        }
        if (color != shown) {
            ret = fill(&lamp, color);
            if (ret != WS2811_SUCCESS) {
                fprintf(stderr, "lamp_pattern: ws2811_render: %s\n", ws2811_get_return_t_str(ret));
                status = 3;
                break;
            }
            shown = color;
        }
        nanosleep(&tick, NULL);
    }
    /* Always try to leave the lamp dark: done, stopped or after a failed frame. */
    ret = fill(&lamp, 0);
    if (ret != WS2811_SUCCESS && status == 0) {
        fprintf(stderr, "lamp_pattern: turning off: %s\n", ws2811_get_return_t_str(ret));
        status = 3;
    }
    ws2811_fini(&lamp);
    return status;
}
