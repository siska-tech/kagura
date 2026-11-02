class Bench {
 static run() {
  var q = []
  for (i in 0...64) { q.add([i, i % 16, i % 4]) }
  var s = 0
  var next = 0
  while (q.count > 0) {
   var e = q.removeAt(0)
   if (e[0] != next) Fiber.abort("FIFO order mismatch")
   s = s + e[0] + e[1] + e[2]
   next = next + 1
  }
  if (next != 64) Fiber.abort("Dropped event")
  return s
 }
}
