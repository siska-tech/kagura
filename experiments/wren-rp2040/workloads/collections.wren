class Bench {
 static run() {
  var xs = []
  var m = {}
  for (i in 0...64) {
   xs.add(i)
   m[i] = i * 2
  }
  var s = 0
  for (i in xs) { s = s + m[i] }
  return s
 }
}
