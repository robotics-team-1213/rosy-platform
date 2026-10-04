package io.github.livsbittt.rosy.pilot

data class Candidate(val host: String, val port: Int, val addresses: List<String>, val name: String = "", val robotId: String = "", val secure: Boolean = true)

/** Presence generation rejects resolves completed after loss; unique-name budget never grows beyond 64. */
class CandidateStore {
    private val seen = mutableSetOf<String>()
    private val present = mutableMapOf<String, Long>()
    private val rows = mutableMapOf<String, Pair<Candidate, Long>>()
    private var generation = 0L
    @Synchronized fun found(name: String): Long? {
        if (name !in seen && seen.size >= 64) return null
        seen.add(name)
        return present.getOrPut(name) { ++generation }
    }
    @Synchronized fun lost(name: String) { present.remove(name); rows.remove(name) }
    @Synchronized fun resolved(name: String, version: Long, row: Candidate) {
        if (present[name] == version) rows[name] = row to System.nanoTime()
    }
    @Synchronized fun fresh(name: String): Boolean = rows[name]?.let { System.nanoTime() - it.second < 60_000_000_000L } == true
    @Synchronized fun records(): List<Candidate> = rows.filterKeys { fresh(it) }.values.map { it.first }.distinct().sortedBy { it.name }
    @Synchronized fun addresses(host: String, port: Int): List<String>? {
        val recent = rows.filterKeys { fresh(it) }.values.map { it.first }.filter { it.host == host }
        if (recent.isEmpty()) return null
        check(recent.all { it.port == port }) { "conflicting service port" }
        check(recent.map { it.secure }.distinct().size == 1) { "conflicting service transport" }
        check(recent.map { it.robotId }.filter { it.isNotEmpty() }.distinct().size <= 1) { "conflicting robot identity" }
        val common = recent.map { it.addresses.toSet() }.reduce { a, b -> a intersect b }
        check(common.isNotEmpty()) { "conflicting service identity" }
        return common.sorted()
    }
    @Synchronized fun matches(candidate: Candidate, robotId: String): Boolean = runCatching {
        addresses(candidate.host, candidate.port) == candidate.addresses.sorted() &&
            rows.filterKeys { fresh(it) }.values.map { it.first }.filter { it.host == candidate.host }.all {
                it.secure == candidate.secure && (it.robotId.isEmpty() || it.robotId == robotId)
            }
    }.getOrDefault(false)
    @Synchronized fun clear() { rows.clear(); present.clear(); seen.clear(); generation++ }
}
