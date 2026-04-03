import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/provisioning_models.dart';
import '../../state/provisioning_controller.dart';
import '../../widgets/wizard_scaffold.dart';

class DeviceSettingsStep extends StatefulWidget {
  const DeviceSettingsStep({super.key});

  @override
  State<DeviceSettingsStep> createState() => _DeviceSettingsStepState();
}

class _DeviceSettingsStepState extends State<DeviceSettingsStep> {
  final _formKey = GlobalKey<FormState>();
  final _tz = TextEditingController(text: 'America/Arizona');
  final _sleepStart = TextEditingController(text: '22:30');
  final _sleepEnd = TextEditingController(text: '06:30');
  final _pollInterval = TextEditingController(text: '15');
  final _deepCleanCron = TextEditingController(text: '0 3 * * 0');
  int _rotation = 90;

  @override
  void dispose() {
    _tz.dispose();
    _sleepStart.dispose();
    _sleepEnd.dispose();
    _pollInterval.dispose();
    _deepCleanCron.dispose();
    super.dispose();
  }

  bool _isTime(String value) => RegExp(r'^\d{2}:\d{2}$').hasMatch(value);

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ProvisioningController>();

    return WizardScaffold(
      title: 'Device settings',
      subtitle: 'Set timezone, sleep window, rotation, and refresh schedule.',
      error: controller.errorMessage,
      child: SingleChildScrollView(
        child: Form(
          key: _formKey,
          child: SizedBox(
            width: 540,
            child: Column(
              children: [
                TextFormField(
                  controller: _tz,
                  decoration: const InputDecoration(
                    labelText: 'Timezone (IANA)',
                    border: OutlineInputBorder(),
                  ),
                  validator: (v) => (v == null || !v.contains('/'))
                      ? 'Use format Area/City'
                      : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _sleepStart,
                  decoration: const InputDecoration(
                    labelText: 'Sleep Start (HH:mm)',
                    border: OutlineInputBorder(),
                  ),
                  validator: (v) => _isTime((v ?? '').trim())
                      ? null
                      : 'Use 24-hour HH:mm format',
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _sleepEnd,
                  decoration: const InputDecoration(
                    labelText: 'Sleep End (HH:mm)',
                    border: OutlineInputBorder(),
                  ),
                  validator: (v) => _isTime((v ?? '').trim())
                      ? null
                      : 'Use 24-hour HH:mm format',
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<int>(
                  initialValue: _rotation,
                  decoration: const InputDecoration(
                    labelText: 'Rotation',
                    border: OutlineInputBorder(),
                  ),
                  items: const [0, 90, 180, 270]
                      .map((r) => DropdownMenuItem(
                            value: r,
                            child: Text('$r°'),
                          ))
                      .toList(),
                  onChanged: (value) => setState(() => _rotation = value ?? 90),
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _pollInterval,
                  decoration: const InputDecoration(
                    labelText: 'Refresh interval (minutes)',
                    border: OutlineInputBorder(),
                  ),
                  keyboardType: TextInputType.number,
                  validator: (v) {
                    final n = int.tryParse((v ?? '').trim());
                    if (n == null || n < 1 || n > 240) {
                      return 'Enter 1 to 240 minutes';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _deepCleanCron,
                  decoration: const InputDecoration(
                    labelText: 'Deep-clean cron (advanced)',
                    border: OutlineInputBorder(),
                  ),
                  validator: (v) => (v == null || v.trim().split(' ').length < 5)
                      ? 'Use a 5-field cron expression'
                      : null,
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    FilledButton(
                      onPressed: controller.isBusy
                          ? null
                          : () async {
                              if (!_formKey.currentState!.validate()) return;
                              controller.formData.settings = DeviceSettings(
                                timezone: _tz.text.trim(),
                                sleepStart: _sleepStart.text.trim(),
                                sleepEnd: _sleepEnd.text.trim(),
                                rotate: _rotation,
                                pollIntervalMinutes:
                                    int.parse(_pollInterval.text.trim()),
                                deepCleanCron: _deepCleanCron.text.trim(),
                              );
                              await controller.sendSettings();
                            },
                      child: const Text('Save Settings to Device'),
                    ),
                    const SizedBox(width: 8),
                    OutlinedButton(
                      onPressed: controller.isBusy ? null : controller.nextStep,
                      child: const Text('Continue'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
