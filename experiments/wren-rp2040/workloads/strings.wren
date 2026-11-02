class Bench {
 static run() {
  var s = ""
  for (i in 0...128) { s = s + "あ" }
  return s.bytes.count
 }
}
