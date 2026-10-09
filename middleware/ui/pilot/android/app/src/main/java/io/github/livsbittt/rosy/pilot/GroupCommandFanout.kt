package io.github.livsbittt.rosy.pilot

import java.util.concurrent.ExecutorService
import java.util.concurrent.TimeUnit

/** Sends one command to both authenticated robots; any refusal requests zero on both. */
class GroupCommandFanout(private val workers: ExecutorService,
    private val first: (String) -> Int, private val second: (String) -> Int) {
    fun send(linear: Double, angular: Double): Boolean {
        val body = "{\"linear\":$linear,\"angular\":$angular}"
        val one = workers.submit<Int> { first(body) }
        val two = workers.submit<Int> { second(body) }
        val acceptedOne = runCatching { one.get(550, TimeUnit.MILLISECONDS) in 200..299 }.getOrDefault(false)
        val acceptedTwo = runCatching { two.get(550, TimeUnit.MILLISECONDS) in 200..299 }.getOrDefault(false)
        val accepted = acceptedOne && acceptedTwo
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
