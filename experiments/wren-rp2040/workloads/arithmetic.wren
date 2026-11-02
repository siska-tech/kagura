class Bench {
 static run() {
  var s = 0
  for (i in 0...10000) { s = s + i }
  return s
 }
}
