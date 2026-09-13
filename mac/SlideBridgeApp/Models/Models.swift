import Foundation

public struct MediaItem: Codable, Identifiable, Hashable {
    public var id: String { path }
    public let path: String
    public let format: String
    public let bytes: Int
    public let ole_preview: Bool

    public var fileName: String {
        URL(fileURLWithPath: path).lastPathComponent
    }

    public var formattedSize: String {
        ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
    }
}

public struct ScanReport: Codable {
    public let source: String
    public let media: [MediaItem]
    public let ole_objects: Int

    public var emfCount: Int {
        media.filter { $0.format.lowercased() == "emf" }.count
    }

    public var wmfCount: Int {
        media.filter { $0.format.lowercased() == "wmf" }.count
    }
}

public struct ConvertedItem: Codable, Identifiable {
    public var id: String { path }
    public let source: String
    public let path: String
    public let bytes: Int
    public let method: String
}

public struct FixReport: Codable {
    public let source: String
    public let output: String
    public let converted: [ConvertedItem]
    public let updated_relationships: [String]?
    public let retained: Int?
}

public struct DoctorCheck: Codable, Identifiable {
    public var id: String { name }
    public let name: String
    public let status: String // "ok", "warn", "fail", "info"
    public let detail: String
    public let fix: String?
}

public struct DoctorReport: Codable {
    public let checks: [DoctorCheck]
    public let failures: Int
    public let warnings: Int
    public let ready: Bool
}

public struct EditActiveReport: Codable {
    public let status: String
    public let presentation: String
    public let slide_index: Int
    public let shape_name: String
    public let member: String
    public let backup: String?
    public let backup_retention_days: Int?
    public let preview_format: String?
    public let message: String?
    public let is_near_identical: Bool?
}

// MARK: - Backups

/// One retained snapshot of a presentation.
///
/// Backups are an undo buffer, not a document the user manages: they live in
/// the app's private store, expire on their own, and are restored from here.
public struct BackupEntry: Codable, Identifiable, Hashable {
    public let id: String
    public let path: String
    public let source: String
    public let created: String
    public let ts: Double
    public let bytes: Int
    public let reason: String

    public var presentationName: String {
        URL(fileURLWithPath: source).lastPathComponent
    }

    public var formattedSize: String {
        ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
    }

    public var displayDate: String {
        BackupEntry.parse(created)
    }

    private static let parser = ISO8601DateFormatter()

    private static let display: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .short
        formatter.timeStyle = .short
        return formatter
    }()

    private static func parse(_ value: String) -> String {
        guard let date = parser.date(from: value) else { return value }
        return display.string(from: date)
    }
}

public struct BackupListReport: Codable {
    public let store: String
    public let presentation: String?
    public let retention_days: Int
    public let max_per_presentation: Int
    public let count: Int
    public let total_bytes: Int
    public let backups: [BackupEntry]

    public var formattedTotalSize: String {
        ByteCountFormatter.string(fromByteCount: Int64(total_bytes), countStyle: .file)
    }
}

public struct BackupRestoreReport: Codable {
    public let status: String
    public let presentation: String
    public let restored: BackupEntry
    public let previous_backup: BackupEntry?
    public let message: String?
}

public struct BackupClearReport: Codable {
    public let presentation: String?
    public let removed_count: Int
    public let removed_bytes: Int

    public var formattedRemovedSize: String {
        ByteCountFormatter.string(fromByteCount: Int64(removed_bytes), countStyle: .file)
    }
}

public enum AppTab: String, CaseIterable, Identifiable {
    case batchRepair = "batchRepair"
    case originEdit = "originEdit"
    case doctor = "doctor"

    public var id: String { rawValue }

    @MainActor
    public func title(using lm: LanguageManager) -> String {
        switch self {
        case .batchRepair: return lm.t(.tabBatchRepair)
        case .originEdit: return lm.t(.tabOriginEdit)
        case .doctor: return lm.t(.tabDoctor)
        }
    }

    public var iconName: String {
        switch self {
        case .batchRepair: return "wand.and.stars"
        case .originEdit: return "chart.xyaxis.line"
        case .doctor: return "stethoscope"
        }
    }
}

public enum UsageMode: String, Codable, CaseIterable, Identifiable {
    case batchOnly = "batchOnly"
    case fullBridge = "fullBridge"

    public var id: String { rawValue }
}
