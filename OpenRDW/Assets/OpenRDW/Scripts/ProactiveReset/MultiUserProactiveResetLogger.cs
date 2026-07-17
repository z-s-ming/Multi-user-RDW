using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

public class MultiUserProactiveResetLogger
{
    private string trialDirectory;
    private int decisionIndex;
    private int resetIndex;

    public bool IsReady
    {
        get { return !string.IsNullOrEmpty(trialDirectory); }
    }

    public void BeginTrial(GlobalConfiguration globalConfiguration, int trialId, ExperimentSetup setup)
    {
        if (globalConfiguration == null || globalConfiguration.statisticsLogger == null)
            return;

        trialDirectory = Path.Combine(
            globalConfiguration.statisticsLogger.RESULT_WITH_TIME_DIRECTORY,
            "Proactive Reset Logs",
            "trialId_" + trialId);
        Directory.CreateDirectory(trialDirectory);

        decisionIndex = 0;
        resetIndex = 0;

        WriteMetadata(globalConfiguration, trialId, setup);
        WriteWaypointLog(setup);
        WriteHeaderIfMissing(
            GetDecisionPath(),
            "decision_index;time;strategy;group_risk;w_h;g_peak;triggered;selected_user_id;selection_reason;eligible_users;individual_risks");
        WriteHeaderIfMissing(
            GetResetEventPath(),
            "reset_index;time;user_id;source;accepted;reason");
        WriteHeaderIfMissing(
            GetUserSamplesPath(),
            "time;user_id;pos_x;pos_y;vel_x;vel_y;individual_risk;is_resetting;is_eligible");
    }

    public void EndTrial()
    {
        trialDirectory = null;
    }

    public void LogDecision(
        float time,
        MultiUserProactiveResetController.Strategy strategy,
        float groupRisk,
        float worsening,
        float peakRisk,
        bool triggered,
        int selectedUserId,
        string selectionReason,
        IList<int> eligibleUserIds,
        IList<float> individualRisks)
    {
        if (!IsReady)
            return;

        var line = new StringBuilder();
        line.Append(decisionIndex++).Append(';');
        line.Append(FloatToString(time)).Append(';');
        line.Append(strategy).Append(';');
        line.Append(FloatToString(groupRisk)).Append(';');
        line.Append(FloatToString(worsening)).Append(';');
        line.Append(FloatToString(peakRisk)).Append(';');
        line.Append(triggered ? "1" : "0").Append(';');
        line.Append(selectedUserId).Append(';');
        line.Append(Sanitize(selectionReason)).Append(';');
        line.Append(Sanitize(JoinInts(eligibleUserIds))).Append(';');
        line.Append(Sanitize(JoinFloats(individualRisks)));
        File.AppendAllText(GetDecisionPath(), line + "\n");
    }

    public void LogResetEvent(float time, int userId, string source, bool accepted, string reason)
    {
        if (!IsReady)
            return;

        var line = string.Format(
            "{0};{1};{2};{3};{4};{5}\n",
            resetIndex++,
            FloatToString(time),
            userId,
            Sanitize(source),
            accepted ? "1" : "0",
            Sanitize(reason));
        File.AppendAllText(GetResetEventPath(), line);
    }

    public void LogUserSamples(
        float time,
        IList<MultiUserRiskWorseningModel.UserSnapshot> users,
        IList<float> individualRisks,
        IList<int> eligibleUserIds)
    {
        if (!IsReady || users == null)
            return;

        var sb = new StringBuilder();
        for (int i = 0; i < users.Count; i++)
        {
            var user = users[i];
            float risk = individualRisks != null && i < individualRisks.Count ? individualRisks[i] : float.NaN;
            bool eligible = ContainsInt(eligibleUserIds, user.UserId);
            sb.Append(FloatToString(time)).Append(';');
            sb.Append(user.UserId).Append(';');
            sb.Append(FloatToString(user.Position.x)).Append(';');
            sb.Append(FloatToString(user.Position.y)).Append(';');
            sb.Append(FloatToString(user.Velocity.x)).Append(';');
            sb.Append(FloatToString(user.Velocity.y)).Append(';');
            sb.Append(FloatToString(risk)).Append(';');
            sb.Append(user.IsResetting ? "1" : "0").Append(';');
            sb.Append(eligible ? "1" : "0").Append('\n');
        }

        File.AppendAllText(GetUserSamplesPath(), sb.ToString());
    }

    private void WriteMetadata(GlobalConfiguration globalConfiguration, int trialId, ExperimentSetup setup)
    {
        var metadataPath = Path.Combine(trialDirectory, "run_metadata.csv");
        var sb = new StringBuilder();
        sb.AppendLine("field;value");
        sb.AppendLine("trial_id;" + trialId);
        sb.AppendLine("program_start_time;" + Sanitize(globalConfiguration.startTimeOfProgram));
        sb.AppendLine("random_seed;" + setup.randomSeed);
        sb.AppendLine("guarantee_experiment_reproducibility;" + globalConfiguration.guaranteeExperimentReproducibility);
        sb.AppendLine("virtual_path_generator_seed;" + VirtualPathGenerator.RANDOM_SEED);
        sb.AppendLine("strategy;" + globalConfiguration.proactiveResetStrategy);
        sb.AppendLine("movement_controller;" + globalConfiguration.movementController);
        sb.AppendLine("run_in_backstage;" + globalConfiguration.runInBackstage);
        sb.AppendLine("use_simulation_time;" + globalConfiguration.useSimulationTime);
        sb.AppendLine("target_fps;" + FloatToString(globalConfiguration.targetFPS));
        sb.AppendLine("avatar_num;" + globalConfiguration.avatarNum);
        sb.AppendLine("tracking_space;" + setup.trackingSpaceChoice);
        sb.AppendLine("square_width;" + FloatToString(setup.squareWidth));
        sb.AppendLine("obstacle_type;" + setup.obstacleType);
        sb.AppendLine("decision_dt;" + FloatToString(globalConfiguration.proactiveDecisionDt));
        sb.AppendLine("theta_w;" + FloatToString(globalConfiguration.proactiveThetaW));
        sb.AppendLine("theta_g;" + FloatToString(globalConfiguration.proactiveThetaG));
        sb.AppendLine("prediction_horizon;" + FloatToString(globalConfiguration.proactivePredictionHorizon));
        sb.AppendLine("prediction_step;" + FloatToString(globalConfiguration.proactivePredictionStep));
        sb.AppendLine("velocity_history_seconds;" + FloatToString(globalConfiguration.proactiveVelocityHistorySeconds));
        sb.AppendLine("proactive_reset_cooldown;" + FloatToString(globalConfiguration.proactiveResetCooldown));
        sb.AppendLine("reset_duration_for_prediction;" + FloatToString(globalConfiguration.proactiveResetDurationForPrediction));
        sb.AppendLine("safe_boundary_distance;" + FloatToString(globalConfiguration.proactiveSafeBoundaryDistance));
        sb.AppendLine("emergency_boundary_distance;" + FloatToString(globalConfiguration.proactiveEmergencyBoundaryDistance));
        sb.AppendLine("safe_pair_distance;" + FloatToString(globalConfiguration.proactiveSafePairDistance));
        sb.AppendLine("severe_pair_distance;" + FloatToString(globalConfiguration.proactiveSeverePairDistance));
        File.WriteAllText(metadataPath, sb.ToString());
    }

    private void WriteWaypointLog(ExperimentSetup setup)
    {
        var path = Path.Combine(trialDirectory, "waypoint_log.csv");
        var sb = new StringBuilder();
        sb.AppendLine("user_id;path_seed_choice;waypoint_index;x;y;initial_x;initial_y;initial_forward_x;initial_forward_y");
        for (int userId = 0; userId < setup.avatars.Count; userId++)
        {
            var avatar = setup.avatars[userId];
            string pathSeedChoice = avatar.pathSeedChoice.ToString();
            float initialX = avatar.initialConfiguration != null ? avatar.initialConfiguration.initialPosition.x : float.NaN;
            float initialY = avatar.initialConfiguration != null ? avatar.initialConfiguration.initialPosition.y : float.NaN;
            float initialForwardX = avatar.initialConfiguration != null ? avatar.initialConfiguration.initialForward.x : float.NaN;
            float initialForwardY = avatar.initialConfiguration != null ? avatar.initialConfiguration.initialForward.y : float.NaN;

            if (avatar.waypoints == null)
                continue;

            for (int waypointIndex = 0; waypointIndex < avatar.waypoints.Count; waypointIndex++)
            {
                Vector2 waypoint = avatar.waypoints[waypointIndex];
                sb.Append(userId).Append(';');
                sb.Append(pathSeedChoice).Append(';');
                sb.Append(waypointIndex).Append(';');
                sb.Append(FloatToString(waypoint.x)).Append(';');
                sb.Append(FloatToString(waypoint.y)).Append(';');
                sb.Append(FloatToString(initialX)).Append(';');
                sb.Append(FloatToString(initialY)).Append(';');
                sb.Append(FloatToString(initialForwardX)).Append(';');
                sb.Append(FloatToString(initialForwardY)).Append('\n');
            }
        }

        File.WriteAllText(path, sb.ToString());
    }

    private void WriteHeaderIfMissing(string path, string header)
    {
        if (!File.Exists(path))
            File.WriteAllText(path, header + "\n");
    }

    private string GetDecisionPath()
    {
        return Path.Combine(trialDirectory, "decision_points.csv");
    }

    private string GetUserSamplesPath()
    {
        return Path.Combine(trialDirectory, "user_samples.csv");
    }

    private string GetResetEventPath()
    {
        return Path.Combine(trialDirectory, "reset_events.csv");
    }

    private string FloatToString(float value)
    {
        if (float.IsNaN(value))
            return "NaN";
        if (float.IsInfinity(value))
            return value > 0 ? "Infinity" : "-Infinity";
        return value.ToString("G9");
    }

    private string JoinInts(IList<int> values)
    {
        if (values == null)
            return "";
        return string.Join("|", values);
    }

    private string JoinFloats(IList<float> values)
    {
        if (values == null)
            return "";

        var parts = new List<string>();
        for (int i = 0; i < values.Count; i++)
            parts.Add(FloatToString(values[i]));
        return string.Join("|", parts);
    }

    private string Sanitize(string value)
    {
        return string.IsNullOrEmpty(value) ? "" : value.Replace(";", ",").Replace("\n", " ").Replace("\r", " ");
    }

    private bool ContainsInt(IList<int> values, int target)
    {
        if (values == null)
            return false;

        for (int i = 0; i < values.Count; i++)
        {
            if (values[i] == target)
                return true;
        }

        return false;
    }
}
