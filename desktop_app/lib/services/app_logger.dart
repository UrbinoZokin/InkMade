import 'package:logging/logging.dart';

class AppLogger {
  static bool _initialized = false;

  static void init() {
    if (_initialized) return;
    _initialized = true;
    Logger.root.level = Level.ALL;
    Logger.root.onRecord.listen((record) {
      // Friendly console format while developing on desktop.
      // ignore: avoid_print
      print(
        '[${record.level.name}] '
        '${record.time.toIso8601String()} '
        '${record.loggerName}: ${record.message}',
      );
    });
  }

  static Logger get(String name) => Logger(name);
}
