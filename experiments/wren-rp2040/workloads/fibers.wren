class Bench {
 static run() {
  var fs = []
  for (i in 0...4) {
   fs.add(Fiber.new {
    for (j in 0...16) { Fiber.yield(j) }
   })
  }
  var s = 0
  for (j in 0...16) {
   for (f in fs) { s = s + f.call() }
  }
  return s
 }
}
