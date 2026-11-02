System.print("こんにちは、神楽！")
class Desktop {
 foreign static open(title)
 foreign static rect(x, y, w, h, color)
 foreign static nextEvent()
 foreign static present()
}
class App {
 static run() {
  var title = "神楽 " + "Desktop"
  if (!Desktop.open(title)) Fiber.abort("open failed")
  title = null
  System.gc()
  var x = 4
  var color = 12
  if (!Desktop.rect(x, 8, 48, 24, color)) Fiber.abort("rectangle rejected")
  if (!Desktop.present()) Fiber.abort("present failed")
  for (i in 1..4) {
   var event = Desktop.nextEvent()
   if (event != i) Fiber.abort("event order mismatch")
   x = x + event
   color = (color + event) % 16
   if (!Desktop.rect(x, 8, 48, 24, color)) Fiber.abort("rectangle rejected")
   if (!Desktop.present()) Fiber.abort("present failed")
  }
  if (Desktop.nextEvent() != 0) Fiber.abort("extra event")
  return x * 100 + color
 }
}
