#ifndef PARTNER_MATCHER_H
#define PARTNER_MATCHER_H
#include "Constants.h"
#include "Student.h"

/**
 * The PartnerMatcher Class. Contains student information to match study partners.
 */
class PartnerMatcher {
private:
    /**
     * A struct to represent a unit of pairing information. Used in the linked list data member mappingHead.
     * The ID of student1 should ALWAYS be smaller than student2's, i.e., student1->getId() < student2->getId() always evaluates to true.
     */
    struct PartnerScoreMappings {
        /**
         * The student with the smaller ID.
         */
        Student *student1;
        /**
         * The student with the larger ID.
         */
        Student *student2;
        /**
         * The partner score between the 2 students.
         */
        double score;
        /**
         * The next pairing in the circular linked list.
         */
        PartnerScoreMappings *next;
        /**
         * The previous pairing in the circular linked list.
         */
        PartnerScoreMappings *prev;
    };

    /**
     * A dynamic array of Course objects that is involved in the PartnerMatcher stored in ascending order by course code.
     * The Course objects are not owned by the PartnerMatcher.
     */
    const Course **courseArray;
    /**
     * An integer denoting the number of courses stored in courseArray.
     */
    int numCourses;

    /**
     * A dynamic array of Student objects that is involved in the PartnerMatcher stored in ascending order by ID.
     * The Student objects are not owned by the PartnerMatcher.
     */
    Student **studentArray;
    /**
     * An integer denoting the number of students stored in studentArray.
     */
    int numStudents;

    /**
     * A circular doubly-linked list storing study partner scores.
     * The pairs should ALWAYS be stored in ascending order of score, then student ID of student1, then student ID of student2.
     *
     * A pairing is considered "smaller" when:
     *   - A mapping has the smaller score
     *   - Should there be a tie in score, the mapping with a smaller student ID of student1 should be pointed at.
     *   - Should there be ties in both score and student1's ID, the mapping with a smaller student ID of student2 should be pointed at.
     *
     * This means, `mappingHead` should always point to the "smallest" mapping.
     *
     * Within each pairing of the circular list, the `next` pointer should always point to the pairing ordered right after itself, or the "smallest" pairing if it is the "largest".
     * Similarly, the `prev` pointer should always point to the pairing ordered right before itself, or the "largest" pairing if it is the "smallest".
     */
    PartnerScoreMappings *mappingHead;

    /**
     * The semester as context of the PartnerMatcher instance.
     */
    Semester semester;
    /**
     * The year as context of the PartnerMatcher instance.
     */
    int year;

public:
    /**
     * Constructs an instance of the PartnerMatcher class.
     * @param semester The semester of the instance is dealing with
     * @param year The year of the instance is dealing with
     */
    PartnerMatcher(Semester semester, int year);

    /**
     * Destructs a PartnerMatcher instance.
     */
    ~PartnerMatcher();

    /**
     * Adds a student to the PartnerMatcher.
     * The Student object should not be owned by the PartnerMatcher, so there is no need to copy the Student objects.
     * @param student The student to add
     * @return A reference to the PartnerMatcher object, convenient for chaining.
     */
    PartnerMatcher& addStudent(Student &student);

    /**
     * Adds a course to the PartnerMatcher.
     * The Course object should not be owned by the PartnerMatcher, so there is no need to copy the Course objects.
     * @param course The course to add
     * @return A reference to the PartnerMatcher object, convenient for chaining.
     */
    PartnerMatcher& addCourse(const Course &course);

    /**
     * (Re)calculates study partner scores between all students pairs.
     */
    void updateMappings();

    /**
     * Matches student partners and assign them accordingly. Do nothing if there are no mappings.
     *
     * Since this function might be called after mappings are updated, you should nullify all existing partner pairings at the beginning of this function.
     *
     * If the given match mode is `MOST_SIMILAR`, then students with the highest mapping score 
     * should be assigned as each other's partners.
     * Otherwise, if the given match mode is <code class="language-cpp">LEAST_SIMILAR</code>,
     * then students with the lowest mapping score should be assigned as each other's partners.
     * Note that each student should only have one partner.
     * @param matchMode The mode to assign partners.
     */
    void matchStudents(MatchMode matchMode) const;

    /**
     * Returns a copy of the PartnerMatcher with the semester moved to the next.
     * @return A **dynamically-allocated** PartnerMatcher object that has the context of the next semester.
     */
    PartnerMatcher& moveToNextSemester() const;

    // The following functions are implemented for you.

    /**
     * Gets the semester of the PartnerMatcher instance's context.
     * @return The semester of the instance
     */
    Semester getSemester() const;

    /**
     * Gets the year of the PartnerMatcher instance's context.
     * @return The year of the instance
     */
    int getYear() const;

    /**
     * Prints the information of all students in the PartnerMatcher instance.
     */
    void printStudents() const;

    /**
     * Prints the calculated scores of partner mappings between students
     */
    void printAllMappings() const;
};

#endif
