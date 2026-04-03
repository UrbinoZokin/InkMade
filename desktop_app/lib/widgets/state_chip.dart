import 'package:flutter/material.dart';

import '../models/provisioning_models.dart';

class StateChip extends StatelessWidget {
  const StateChip({super.key, required this.message});

  final DeviceStateMessage? message;

  @override
  Widget build(BuildContext context) {
    final state = message?.state ?? 'no_state_yet';
    return Chip(
      avatar: const Icon(Icons.bluetooth_connected, size: 18),
      label: Text('Device state: $state'),
    );
  }
}
