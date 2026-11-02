class Item {
 construct new(v) { _v = v }
 value { _v }
}
class Bench {
 static run() {
  var s = 0
  for (i in 0...256) { s = s + Item.new(i).value }
  return s
 }
}
