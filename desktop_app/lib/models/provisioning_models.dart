import 'dart:convert';

enum WizardStep {
  scanConnect,
  pairPin,
  wifi,
  googleAuth,
  icloud,
  deviceSettings,
  reviewApply,
}

class BleDeviceSummary {
  const BleDeviceSummary({required this.id, required this.name, this.rssi});

  final String id;
  final String name;
  final int? rssi;
}

class DeviceSettings {
  DeviceSettings({
    this.timezone = 'America/Arizona',
    this.sleepStart = '22:30',
    this.sleepEnd = '06:30',
    this.rotate = 90,
    this.pollIntervalMinutes = 15,
    this.deepCleanCron = '0 3 * * 0',
  });

  String timezone;
  String sleepStart;
  String sleepEnd;
  int rotate;
  int pollIntervalMinutes;
  String deepCleanCron;

  Map<String, dynamic> toJsonCommand() {
    return {
      'op': 'settings_set',
      'timezone': timezone,
      'sleep_start': sleepStart,
      'sleep_end': sleepEnd,
      'rotate': rotate,
      'poll_interval_minutes': pollIntervalMinutes,
      'deep_clean_cron': deepCleanCron,
    };
  }
}

class DeviceStateMessage {
  DeviceStateMessage({
    required this.state,
    this.ip,
    this.error,
    this.verificationUrl,
    this.userCode,
    this.expiresIn,
    this.interval,
    this.calendars = const <String>[],
  });

  final String state;
  final String? ip;
  final String? error;
  final String? verificationUrl;
  final String? userCode;
  final int? expiresIn;
  final int? interval;
  final List<String> calendars;

  factory DeviceStateMessage.fromJson(Map<String, dynamic> json) {
    return DeviceStateMessage(
      state: json['state']?.toString() ?? 'unknown',
      ip: json['ip']?.toString(),
      error: json['error']?.toString(),
      verificationUrl: json['verification_url']?.toString(),
      userCode: json['user_code']?.toString(),
      expiresIn: (json['expires_in'] as num?)?.toInt(),
      interval: (json['interval'] as num?)?.toInt(),
      calendars: (json['calendars'] as List<dynamic>? ?? const <dynamic>[])
          .map((e) => e.toString())
          .toList(),
    );
  }

  static DeviceStateMessage? tryParse(String raw) {
    try {
      final dynamic decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) {
        return null;
      }
      return DeviceStateMessage.fromJson(decoded);
    } catch (_) {
      return null;
    }
  }
}

class ProvisioningFormData {
  String pin = '';
  String wifiSsid = '';
  String wifiPassword = '';
  String iCloudUser = '';
  String iCloudAppPassword = '';
  DeviceSettings settings = DeviceSettings();
}
