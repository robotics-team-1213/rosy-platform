package io.github.livsbittt.rosy.pilot

object PilotColors {
    private fun Color(arg: Long) = arg.toInt()
    val background = Color(0xFF101214) // --ground
    val foreground = Color(0xFFEEEEEF) // --ink
    val muted = Color(0xFF9499A0) // --ink-quiet
    val rose = Color(0xFFF697E7) // --brand-rose
    val card = Color(0xFF2B2D30) // --ground-card
    val pressed = Color(0xFF35383C) // --ground-card-2
    val disabled = Color(0xFF1D1F21) // --ground-soft
}
