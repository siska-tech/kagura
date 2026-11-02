class Bench {
 static run() {
  var s = 0
  for (i in 0...100) {
   var tmp = List.filled(32, i)
   s = s + tmp[31]
  }
  return s
 }
}
