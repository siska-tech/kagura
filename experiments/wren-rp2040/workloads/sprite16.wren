class Bench {
 static run() {
  var pixels = List.filled(256, 0)
  for (pass in 0...4) {
   for (y in 0...16) {
    for (x in 0...16) { pixels[y * 16 + x] = (x + y + pass) % 16 }
   }
  }
  var checksum = 0
  for (y in 0...16) {
   for (x in 0...16) {
    if (pixels[y * 16 + x] != (x + y + 3) % 16) Fiber.abort("Pixel mismatch")
   }
  }
  for (p in pixels) { checksum = checksum + p }
  return checksum
 }
}
