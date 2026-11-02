class Native {
 foreign static add(x)
}
class Bench {
 static run() {
  var s = 0
  for (i in 0...1000) { s = Native.add(s) }
  return s
 }
}
