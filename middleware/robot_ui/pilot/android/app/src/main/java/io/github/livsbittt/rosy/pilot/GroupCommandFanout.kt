package io.github.livsbittt.rosy.pilot

import java.util.concurrent.ExecutorService
import java.util.concurrent.TimeUnit

/** Web link.js IDLE_ZERO_REPEATS: a few zeros after release cover a late motion, then silence; CORE's teleop watchdog holds zero. */
const val IDLE_ZERO_REPEATS = 3

/** Sends one command to both authenticated robots; any refusal requests zero on both. Called from one drive thread. */
class GroupCommandFanout(private val workers: ExecutorService,
    private val first: (String) -> Int, private val second: (String) -> Int) {
    private var zeroStreak = 0

    fun send(linear: Double, angular: Double): Boolean {
        val zero = linear == 0.0 && angular == 0.0
        if (zero && zeroStreak >= IDLE_ZERO_REPEATS) return true   // released and already delivered: stay silent
        val body = "{\"linear\":$linear,\"angular\":$angular}"
        val one = workers.submit<Int> { first(body) }
        val two = workers.submit<Int> { second(body) }
        val acceptedOne = runCatching { one.get(550, TimeUnit.MILLISECONDS) in 200..299 }.getOrDefault(false)
        val acceptedTwo = runCatching { two.get(550, TimeUnit.MILLISECONDS) in 200..299 }.getOrDefault(false)
        val accepted = acceptedOne && acceptedTwo
        zeroStreak = if (accepted && zero) zeroStreak + 1 else 0
        if (!accepted) stop()
        return accepted
    }

    fun stop() {
        val zero = "{\"linear\":0,\"angular\":0}"
        val one = workers.submit { runCatching { first(zero) } }
        val two = workers.submit { runCatching { second(zero) } }
        runCatching { one.get(600, TimeUnit.MILLISECONDS) }
        runCatching { two.get(600, TimeUnit.MILLISECONDS) }
    }
}
