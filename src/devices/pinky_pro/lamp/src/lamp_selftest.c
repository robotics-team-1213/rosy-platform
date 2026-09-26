/*
 * lamp_selftest: light the Pinky Pro WS2812 lamp dim red, green, blue for one
 * second each, then turn it off (D-247 decision 6).
 *
 * Run as root by rosy-hw-test.service when an administrator presses the lamp
 * test on the dashboard; a person then says whether the light was seen. No ROS,
 * no arguments. It uses the same rpi_ws281x library and the same strip settings
 * as main_node (8 LEDs, GPIO19, GRB). On the Pi 5 the library drives the lamp
 * through /dev/ws281x_pwm (the rp1_ws281x_pwm kernel module, pwm_channel=3).
 *
 * Exit codes: 0 shown and turned off, 2 the library would not start, 3 a frame
 * failed to render. Errors go to stderr, which the caller keeps for its result.
 */
#define _POSIX_C_SOURCE 200809L

#include <signal.h>
#include <stdio.h>
#include <time.h>

#include "ws2811/ws2811.h"

#define LAMP_GPIO 19
#define LAMP_COUNT 8
#define LAMP_DMA 10
#define STEP_MS 1000
#define TICK_MS 50

static volatile sig_atomic_t stop_requested = 0;

static void on_signal(int signum)
{
    (void)signum;
    stop_requested = 1;
}

static void pause_ms(int total_ms)
{
    struct timespec tick = {0, TICK_MS * 1000000L};
    for (int waited = 0; waited < total_ms && !stop_requested; waited += TICK_MS) {
        nanosleep(&tick, NULL);
    }
}

static ws2811_return_t fill(ws2811_t *lamp, ws2811_led_t color)
{
    for (int i = 0; i < LAMP_COUNT; i++) {
        lamp->channel[0].leds[i] = color;
    }
    return ws2811_render(lamp);
}

int main(void)
{
    /* 0xWWRRGGBB, dim: a test, not a torch. */
    static const ws2811_led_t colors[] = {0x00300000, 0x00003000, 0x00000030};
    ws2811_t lamp = {
        .freq = WS2811_TARGET_FREQ,
        .dmanum = LAMP_DMA,
        .channel = {
            [0] = {
                .gpionum = LAMP_GPIO,
                .invert = 0,
                .count = LAMP_COUNT,
                .strip_type = WS2811_STRIP_GRB,
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
        fprintf(stderr, "lamp_selftest: ws2811_init: %s\n", ws2811_get_return_t_str(ret));
        return 2;
    }
    int status = 0;
    for (size_t step = 0; step < sizeof(colors) / sizeof(colors[0]) && !stop_requested; step++) {
        ret = fill(&lamp, colors[step]);
        if (ret != WS2811_SUCCESS) {
            fprintf(stderr, "lamp_selftest: ws2811_render: %s\n", ws2811_get_return_t_str(ret));
            status = 3;
            break;
        }
        pause_ms(STEP_MS);
    }
    /* Always try to leave the lamp dark, also after a failed frame or a signal. */
    ret = fill(&lamp, 0);
    if (ret != WS2811_SUCCESS && status == 0) {
        fprintf(stderr, "lamp_selftest: turning off: %s\n", ws2811_get_return_t_str(ret));
        status = 3;
    }
    ws2811_fini(&lamp);
    return status;
}
