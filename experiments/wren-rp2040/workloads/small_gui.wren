System.print("Hello World")
System.print("こんにちは、神楽！")
class Native {
 foreign static add(x)
}
class App {
 construct new() {
  _title = "こんにちは、神楽！"
  _rect = [0, 0, 160, 100]
  _events = [0, 1, 2, 3]
 }
 step() {
  var x = 0
  for (event in _events) { x = Native.add(x) }
  _rect[0] = x
  if (_rect[0] != 4 || _rect[2] != 160) Fiber.abort("GUI model mismatch")
  return x + _title.codePoints.count + _rect[2]
 }
}
var GuiApp = App.new()
class Bench {
 static run() { GuiApp.step() }
}
